#!/usr/bin/env python3
"""
PRO1 web surface <-> OpenMixerControl bridge.

Browsers talk JSON over a WebSocket (nginx proxies /ws here); OMC talks OSC over UDP
(OscServer on :10032, which feeds every parameter change back to its client on :10033).

  browser -> bridge   {"op": "set"|"change"|"toggle"|"get", "p": "<osc path>", "i": <1-based index>, "v": <value>}
                      {"op": "watch", "items": [["fader", 1], ...]}   values the page shows
                      {"op": "poll",  "items": [["ch_meter", 1], ...]} values to poll (meters are silent in OMC)
                      {"op": "vegas", "a": "in", "f": "ssf", "v": [...]} Vegas mode (docs/45): /vegas/<a> to OMC
  bridge -> browser   {"u": [["<path>", <index>, <value>], ...]}       updates, batched
                      {"omc": true|false}                              OMC answers / does not answer
                      {"vegas": ["/vegas/<cmd>", [args]]}              Vegas mode, forwarded at once

The bridge keeps the last value of everything it has seen, so a new page gets a snapshot at once.
OMC's OSC server binds UDP 10032 once, at start, with no retry: if another OMC instance (a
simulator) holds the port then, the console never listens and every key goes nowhere. The bridge
asks OMC for one value every second and tells the pages when the answers stop.
"""
import asyncio
import collections
import json
import logging
import os
import socket
import struct

import websockets

OMC = (os.environ.get('OMC_HOST', '127.0.0.1'), int(os.environ.get('OMC_OSC_PORT', '10032')))
LISTEN_PORT = int(os.environ.get('OMC_FEED_PORT', '10033'))
WS_HOST = os.environ.get('BRIDGE_HOST', '127.0.0.1')
WS_PORT = int(os.environ.get('BRIDGE_PORT', '8081'))
POLL_HZ = float(os.environ.get('BRIDGE_POLL_HZ', '12'))
HEALTH_S = 3.0              # no datagram from OMC for this long: OMC is not answering

log = logging.getLogger('omc-surface-simulator-bridge')
VEGAS_OUT = ('inv', 'inv_end', 'in', 'op', 'start')   # what a page may send to OMC's /vegas


# ---- OSC (just what OMC speaks: "f" and "s" arguments)

def _pad(b):
    return b + b'\0' * (4 - len(b) % 4)


def osc_message(address, fmt='', *args):
    out = _pad(address.encode()) + _pad((',' + fmt).encode())
    for f, a in zip(fmt, args):
        if f == 'f':
            out += struct.pack('>f', float(a))
        elif f == 'i':
            out += struct.pack('>i', int(a))
        else:
            out += _pad(str(a).encode())
    return out


def osc_parse(data):
    i = data.index(b'\0')
    address = data[:i].decode(errors='replace')
    j = (i + 4) & ~3
    k = data.index(b'\0', j)
    fmt = data[j + 1:k].decode()
    j = (k + 4) & ~3
    values = []
    for f in fmt:
        if f == 'f':
            values.append(struct.unpack('>f', data[j:j + 4])[0])
            j += 4
        elif f == 'i':
            values.append(struct.unpack('>i', data[j:j + 4])[0])
            j += 4
        elif f == 's':
            e = data.index(b'\0', j)
            values.append(data[j:e].decode(errors='replace'))
            j = (e + 4) & ~3
    return address, values


class Bridge(asyncio.DatagramProtocol):
    def __init__(self):
        self.transport = None
        self.clients = set()
        self.values = {}            # (path, index) -> value
        self.poll = {}              # websocket -> set of (path, index)
        self.pending = []
        # reads are paced: OMC drains its socket at a fixed rate, and a burst of reads (a page
        # loading or changing banks asks for hundreds of values) must not overflow it and push a
        # key press off the end. Writes go out at once; reads queue, de-duplicated.
        self.reads = collections.OrderedDict()   # FIFO: oldest request first, no starvation
        self.last_rx = 0.0          # loop time of OMC's last datagram
        self.alive = None           # OMC answering, as last told to the pages

    # UDP from OMC
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        # only OMC's feed: anything else on :10033 could push fake values to every page
        if addr[0] != OMC[0] and not (OMC[0] in ('127.0.0.1', 'localhost') and addr[0].startswith('127.')):
            return
        try:
            address, values = osc_parse(data)
        except (ValueError, struct.error, IndexError):
            return
        if address.startswith('/vegas/'):
            # Vegas mode: pattern clock and element drives, not values; straight to the pages
            self.last_rx = asyncio.get_running_loop().time()
            if self.clients:
                websockets.broadcast(list(self.clients), json.dumps({'vegas': [address, values]}))
            return
        parts = address.strip('/').split('/')
        if len(parts) != 3 or parts[0] != 'set' or not values or not parts[2].isdigit():
            return
        self.last_rx = asyncio.get_running_loop().time()
        v = values[0]
        if isinstance(v, float):
            v = round(v, 4)
        key = (parts[1], int(parts[2]))
        self.values[key] = v
        self.pending.append([key[0], key[1], v])

    def read(self, p, i):
        k = (str(p), int(i))
        if k not in self.reads:
            self.reads[k] = True

    async def read_loop(self):
        while True:
            await asyncio.sleep(0.01)
            for _ in range(min(16, len(self.reads))):
                (p, i), _v = self.reads.popitem(last=False)
                self.send('get', p, i)

    def send(self, op, p, i, v=None):
        if v is None:
            msg = osc_message(f'/{op}/{p}/{int(i)}')
        elif isinstance(v, str):
            msg = osc_message(f'/{op}/{p}/{int(i)}', 's', v)
        else:
            msg = osc_message(f'/{op}/{p}/{int(i)}', 'f', float(v))
        self.transport.sendto(msg, OMC)

    async def flush_loop(self):
        while True:
            await asyncio.sleep(0.03)
            if self.pending and self.clients:
                batch, self.pending = self.pending, []
                text = json.dumps({'u': batch})
                # broadcast does not wait for slow clients (one stalled browser must not stop the rest)
                websockets.broadcast(list(self.clients), text)
            elif not self.clients:
                self.pending = []

    async def health_loop(self):
        # OMC answers every read: one a second shows whether it is listening at all
        loop = asyncio.get_running_loop()
        while True:
            self.read('screen', 1)
            await asyncio.sleep(1.0)
            alive = loop.time() - self.last_rx < HEALTH_S
            if alive != self.alive:
                self.alive = alive
                log.info('OMC %s', 'answering' if alive else 'NOT answering on %s:%d' % OMC)
                if self.clients:
                    websockets.broadcast(list(self.clients), json.dumps({'omc': alive}))

    async def poll_loop(self):
        while True:
            await asyncio.sleep(1.0 / POLL_HZ)
            items = set()
            for s in self.poll.values():
                items |= s
            for p, i in items:
                self.read(p, i)

    async def handle(self, ws):
        self.clients.add(ws)
        self.poll[ws] = set()
        log.info('client %s', ws.remote_address)
        try:
            if self.alive is not None:
                await ws.send(json.dumps({'omc': self.alive}))
            if self.values:
                await ws.send(json.dumps({'u': [[k[0], k[1], v] for k, v in self.values.items()]}))
            async for text in ws:
                try:
                    m = json.loads(text)
                    if not isinstance(m, dict):
                        continue
                    self.dispatch(ws, m)
                except (ValueError, KeyError, TypeError) as ex:
                    # a malformed message is dropped, the page stays connected
                    log.info('bad message from %s: %s', ws.remote_address, ex)
        finally:
            self.clients.discard(ws)
            self.poll.pop(ws, None)

    def dispatch(self, ws, m):
        op = m.get('op')
        if op == 'get':
            self.read(m['p'], m.get('i', 1))
        elif op in ('set', 'change', 'toggle', 'reset'):
            # values come back only through OMC's change feed: what the pages show is what OMC holds
            v = m.get('v')
            if v is not None and not isinstance(v, (int, float, str)):
                raise TypeError('value must be a number or a string')
            self.send(op, str(m['p']), int(m.get('i', 1)), v)
        elif op == 'watch':
            for p, i in m.get('items', [])[:2000]:
                self.read(p, i)
        elif op == 'vegas':
            a, f, v = str(m['a']), str(m.get('f', '')), m.get('v', [])
            if a not in VEGAS_OUT or not isinstance(v, list) or len(f) != len(v) or any(c not in 'sfi' for c in f):
                raise ValueError('bad vegas message')
            self.transport.sendto(osc_message('/vegas/' + a, f, *v), OMC)
        elif op == 'poll':
            self.poll[ws] = {(str(p), int(i)) for p, i in m.get('items', [])[:400]}

async def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
    loop = asyncio.get_running_loop()
    bridge = Bridge()
    # one socket both sends to OMC and receives its feed: OMC answers the sender's address on :10033
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)   # bursts (Vegas mode, a bank load); capped by rmem_max
    sock.bind(('0.0.0.0', LISTEN_PORT))
    await loop.create_datagram_endpoint(lambda: bridge, sock=sock)
    asyncio.create_task(bridge.flush_loop())
    asyncio.create_task(bridge.poll_loop())
    asyncio.create_task(bridge.read_loop())
    asyncio.create_task(bridge.health_loop())
    async with websockets.serve(bridge.handle, WS_HOST, WS_PORT, max_size=2 ** 20):
        log.info('bridge ws://%s:%d <-> osc %s:%d (feed :%d)', WS_HOST, WS_PORT, OMC[0], OMC[1], LISTEN_PORT)
        await asyncio.Future()


if __name__ == '__main__':
    asyncio.run(main())
