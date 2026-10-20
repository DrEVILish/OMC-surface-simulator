#!/bin/bash
# Generate every model's surface from the vendor drawings (the drawings stay local; the output is committed; docs/25):
#   deploy/gen-surfaces.sh /opt/stored-image [workdir]
# PRO1.dwg -> www/panel.svg + www/controls.json; PRO2-Control-Centre.dwg -> www/models/pro2 and
# www/models/pro2c (derived); PROx-Control-Centre.dwg -> www/models/prox; www/models/index.json lists
# the models made. Needs LibreDWG (dwg2dxf, dwgread; built from the GNU release, docs/25), ezdxf and
# python3-opencv. A drawing that is missing is skipped. NICE="nice -n 10 taskset -c 3,4" pins it.
set -e
SRC=${1:?usage: gen-surfaces.sh <drawings dir> [workdir]}
cd "$(dirname "$0")/.."
WORK=${2:-$(mktemp -d)}
mkdir -p "$WORK" www/models
RUN=${NICE:-}
made=()
dxf() {   # dxf <name> -> $WORK/<name>.dxf (+ JSON for dwgfill)
  $RUN dwg2dxf -y -o "$WORK/$1.dxf" "$SRC/$1.dwg" > "$WORK/$1.log" 2>&1
}
if [ -f "$SRC/PRO1.dwg" ]; then
  dxf PRO1
  $RUN python3 -I gen-surface.py "$WORK/PRO1.dxf" www
fi
if [ -f "$SRC/PRO2-Control-Centre.dwg" ] && [ -f www/controls.json ]; then
  dxf PRO2-Control-Centre
  # LibreDWG's DXF writer drops the panel's group blocks: put them back from its JSON dump
  $RUN dwgread -O JSON -o "$WORK/PRO2.json" "$SRC/PRO2-Control-Centre.dwg" > /dev/null 2>&1
  $RUN python3 -I dwgfill.py "$WORK/PRO2-Control-Centre.dxf" "$WORK/PRO2.json" "$WORK/PRO2-filled.dxf"
  for m in pro2 pro2c; do
    mkdir -p www/models/$m
    $RUN python3 -I gen-surface.py --model $m "$WORK/PRO2-filled.dxf" www/models/$m www/controls.json
    made+=("\"$m\"")
  done
fi
if [ -f "$SRC/PROx-Control-Centre.dwg" ] && [ -f www/controls.json ]; then
  dxf PROx-Control-Centre
  mkdir -p www/models/prox
  $RUN python3 -I gen-surface.py --model prox "$WORK/PROx-Control-Centre.dxf" www/models/prox www/controls.json
  made+=("\"prox\"")
fi
MANUALS=${MANUALS:-$SRC/../Service Manuals}
WING_MANUAL=${WING_MANUAL:-$SRC/../wing-other/wing-user-manual-2025-10-20/User-Manual_WING-series_2025-10-20.pdf}
gen() {   # gen <id> <dxf>
  mkdir -p www/models/$1
  $RUN python3 -I gen-surface.py --model $1 "$2" www/models/$1 www/controls.json
  made+=("\"$1\"")
}
filled() {   # filled <name>: DWG -> DXF with the blocks LibreDWG drops put back
  dxf $1
  $RUN dwgread -O JSON -o "$WORK/$1.json" "$SRC/$1.dwg" > /dev/null 2>&1
  $RUN python3 -I dwgfill.py "$WORK/$1.dxf" "$WORK/$1.json" "$WORK/$1-filled.dxf"
  rm -f "$WORK/$1.json"
}
if [ -f www/controls.json ]; then
  [ -f "$SRC/XL8_mcj.dwg" ] && { dxf XL8_mcj; gen xl8 "$WORK/XL8_mcj.dxf"; }
  [ -f "$SRC/X32.dxf" ] && gen x32 "$SRC/X32.dxf"
  if [ -f "$MANUALS/X32-Compact-Manual.pdf" ]; then
    # page 72 "Dimensions", the TOP view: 512.13 mm drawn 234.17 pt wide
    $RUN python3 -I pdf2dxf.py "$MANUALS/X32-Compact-Manual.pdf" 72 "$WORK/X32C.dxf" --scale 2.18697 --clip 40 70 352 315
    gen x32c "$WORK/X32C.dxf"
  fi
  [ -f "$SRC/X32RACK.dxf" ] && gen x32r "$SRC/X32RACK.dxf"
  [ -f "$SRC/M32_Live.dwg" ] && { filled M32_Live; gen m32 "$WORK/M32_Live-filled.dxf"; }
  [ -f "$SRC/M32R.dwg" ] && { filled M32R; gen m32r "$WORK/M32R-filled.dxf"; }
  if [ -f "$SRC/WING-Dimensional.pdf" ]; then
    # the "console top" view, drawn sideways: 870 mm (the published width) over 345.0 pt
    $RUN python3 -I pdf2dxf.py "$SRC/WING-Dimensional.pdf" 1 "$WORK/WING.dxf" --scale 2.522 --rotate 270 --clip 491.6 373.0 723.4 718.6
    gen wing "$WORK/WING.dxf"
    if [ -f "$WING_MANUAL" ]; then
      $RUN python3 -I compose-wing.py "$WORK/WING.dxf" "$WING_MANUAL" "$WORK"
      gen wingc "$WORK/WINGC.dxf"
      gen wingr "$WORK/WINGR.dxf"
    fi
  fi
fi
(IFS=,; echo "[${made[*]}]") > www/models/index.json
echo "models: $(cat www/models/index.json)"
