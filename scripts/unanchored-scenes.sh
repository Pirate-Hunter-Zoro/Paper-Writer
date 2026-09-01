#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# unanchored-scenes.sh -- which kept pictures were drawn with no reference art.
#
# Scene images carry no `.sources` sidecar (sheets do), so after the fact there
# is no way to tell from the artifacts whether a picture was conditioned on a
# character's reference sheet or drawn from prose alone. The log knows: a render
# that used references says "conditioned on N reference picture(s)".
#
# Why it matters: a scene drawn without its character's sheet is weakly anchored
# for ever unless somebody redraws it. That happens routinely when Gemini refuses
# an upload, and it happened wholesale during the outage that began about 17:00
# on 2026-08-31, when uploads stopped working entirely and sheets for newly
# introduced characters could not be made at all.
#
# To redraw one: delete the image and its `.retry` sidecar and the illustrator
# picks it up again from rung 0.
#
#     rm state/series/<sid>/book/1/images/ch18_4.png*
# ---------------------------------------------------------------------------
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

python3 - "${1:-state/illustrator.log}" <<'PY'
import re, sys
lines = open(sys.argv[1], errors="replace").read().splitlines()
withref, without, last = [], [], None
for l in lines:
    if "drew " in l and "through the browser session" in l:
        last = ("conditioned on" in l, l[1:20])
    m = re.search(r"rendered (ch\d+_\d+)\.png", l)
    if m and last is not None:
        (withref if last[0] else without).append((m.group(1), last[1]))
        last = None
print(f"kept with reference art : {len(withref)}")
print(f"kept from prose alone   : {len(without)}")
if without:
    print("\nredraw candidates (rm the .png and its .retry):")
    for n, t in without:
        print(f"  {n:10} drawn {t}")
PY
