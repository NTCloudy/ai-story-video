"""Re-render a Short from its assets.zip (pictures + narration + timings) without any new AI calls.

python -m storyvideo.rerender assets.zip --out out_rerender
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

from . import render


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="storyvideo.rerender")
    p.add_argument("assets", help="assets.zip from a Short's GitHub Release")
    p.add_argument("--out", default="out_rerender")
    args = p.parse_args(argv)
    out = Path(args.out)
    src = out / "work" / "assets"
    src.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.assets) as z:
        z.extractall(src)
    spec = json.loads((src / "render.json").read_text(encoding="utf-8"))
    imgs = [[src / "images" / n for n in sc["images"]] for sc in spec["scenes"]]
    nars = [{"audio": src / "audio" / sc["audio"], "cues": [tuple(c) for c in sc["cues"]],
             "words": [tuple(w) for w in sc.get("words", [])]} for sc in spec["scenes"]]
    render.configure("short")
    render.assemble(spec["title"], imgs, nars, out / "work", out, hook=spec.get("hook", ""),
                    switch_words=[sc.get("switch_word", "") for sc in spec["scenes"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
