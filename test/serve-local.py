#!/usr/bin/env python3
"""
Local test rig for the PRO1 web surface: the page (www/) and the bridge on one port, 127.0.0.1 only.

On the console, nginx serves www/ and proxies /ws to bridge.py (deploy/). For a simulator on a
workstation this does both in one process, so a headless browser can open http://127.0.0.1:<port>/
and talk to an OMC simulator whose OSC server listens on 127.0.0.1 (OMC_OSC_BIND=127.0.0.1).

usage: OMC_OSC_PORT=41032 OMC_FEED_PORT=41033 python3 test/serve-local.py [--port 48080]
       (controls.json and panel.svg must exist in www/: gen-surface.py writes them)
"""
import argparse
import asyncio
import importlib.util
import logging
import mimetypes
import os
import socket

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

HERE = os.path.dirname(os.path.abspath(__file__))
WWW = os.path.join(HERE, '..', 'www')


def load_bridge():
    spec = importlib.util.spec_from_file_location('bridge', os.path.join(HERE, '..', 'bridge.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def static(connection, request):
    path = request.path.split('?')[0]
    if path == '/ws':
        return None
    name = 'index.html' if path in ('', '/') else path.lstrip('/')
    full = os.path.realpath(os.path.join(WWW, name))
    if not full.startswith(os.path.realpath(WWW) + os.sep) or not os.path.isfile(full):
        return connection.respond(404, 'not found\n')
    with open(full, 'rb') as f:
        body = f.read()
    ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
    return Response(200, 'OK', Headers([('Content-Type', ctype), ('Content-Length', str(len(body))),
                                        ('Cache-Control', 'no-store')]), body)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=48080)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
    bridge_mod = load_bridge()
    loop = asyncio.get_running_loop()
    bridge = bridge_mod.Bridge()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)   # bursts (Vegas mode, a bank load); capped by rmem_max
    sock.bind(('127.0.0.1', bridge_mod.LISTEN_PORT))
    await loop.create_datagram_endpoint(lambda: bridge, sock=sock)
    for task in (bridge.flush_loop, bridge.poll_loop, bridge.read_loop, bridge.health_loop):
        asyncio.create_task(task())
    async with serve(bridge.handle, '127.0.0.1', args.port, process_request=static, max_size=2 ** 20):
        logging.info('http://127.0.0.1:%d/  <->  osc %s:%d (feed :%d)', args.port, *bridge_mod.OMC, bridge_mod.LISTEN_PORT)
        await asyncio.Future()


if __name__ == '__main__':
    asyncio.run(main())
