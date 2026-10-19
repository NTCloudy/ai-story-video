"""Re-render a Short from its assets.zip (pictures + narration + timings) without any new AI calls.

python -m storyvideo.rerender assets.zip --out out_rerender
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

from . import render


def check_only(src: Path, spec: dict, script: Path | None) -> int:
    """Run the Gemini picture check on every picture of the assets (prompts from render.json or script.json)."""
    from . import images
    scenes_src = json.loads(script.read_text(encoding="utf-8"))["scenes"] if script else []
    bad = 0
    for i, sc in enumerate(spec["scenes"]):
        prompts = sc.get("prompts") or ([scenes_src[i].get("image_prompt", ""), scenes_src[i].get("image_prompt_2", "")]
                                        if i < len(scenes_src) else [])
        for k, name in enumerate(sc["images"]):
            ok, problem = images.check_image(src / "images" / name, prompts[k] if k < len(prompts) else "")
            bad += not ok
            print(f"{'✅' if ok else '❌'} {name}: {problem or 'ok'}")
    print(f"{bad} picture(s) flagged")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="storyvideo.rerender")
    p.add_argument("assets", help="assets.zip from a Short's GitHub Release")
    p.add_argument("--out", default="out_rerender")
    p.add_argument("--check-only", action="store_true", help="only run the Gemini picture check")
    p.add_argument("--script", default="", help="script.json (image prompts) for older assets")
    args = p.parse_args(argv)
    out = Path(args.out)
    src = out / "work" / "assets"
    src.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.assets) as z:
        z.extractall(src)
    spec = json.loads((src / "render.json").read_text(encoding="utf-8"))
    if args.check_only:
        return check_only(src, spec, Path(args.script) if args.script else None)
    imgs = [[src / "images" / n for n in sc["images"]] for sc in spec["scenes"]]
    nars = [{"audio": src / "audio" / sc["audio"], "cues": [tuple(c) for c in sc["cues"]],
             "words": [tuple(w) for w in sc.get("words", [])]} for sc in spec["scenes"]]
    render.configure("short")
    render.assemble(spec["title"], imgs, nars, out / "work", out, hook=spec.get("hook", ""),
                    switch_words=[sc.get("switch_word", "") for sc in spec["scenes"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
