"""Free "living photo" motion for still pictures (no paid video model).

1. Depth Anything V2 (small, ONNX, runs on CPU) estimates how near every pixel is.
2. A slow virtual camera move (push-in, pull-out, drift, rise) shifts near pixels more than far ones,
   so the picture gets real depth / parallax instead of a flat pan-and-zoom.
3. A few soft light motes drift through the frame (nearer ones move faster) to add life.
Frames are generated with numpy + OpenCV and piped straight into ffmpeg.

Optional: when numpy / opencv / onnxruntime or the model are missing, available() is False and the
renderer falls back to the plain ffmpeg zoompan motion.
"""

from __future__ import annotations

import math
import os
import random
import subprocess
import urllib.request
from pathlib import Path

MODEL_URL = "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model.onnx"
MODEL_PATH = Path(os.environ.get("DEPTH_MODEL",
                                 str(Path.home() / ".cache" / "storyvideo" / "depth_anything_v2_small.onnx")))
MOVES = ("push_in", "drift_right", "pull_out", "drift_left", "rise")
MARGIN = 1.14      # canvas is 14% larger than the frame so camera moves never reveal an edge
ZOOM = 0.15        # push-in growth of the nearest pixels over one shot (far pixels grow ~1/3 of that)
SHIFT = 0.055      # lateral parallax of the nearest pixels over one shot, as a fraction of the frame width
MOTES = 30

_session = None


def available() -> bool:
    if os.environ.get("STORYVIDEO_MOTION", "").lower() == "zoompan":
        return False
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return _ensure_model()


def _ensure_model() -> bool:
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 10_000_000:
        return True
    try:
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = MODEL_PATH.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URL, tmp)
        tmp.rename(MODEL_PATH)
        return True
    except Exception as e:
        print(f"[動態] 景深模型下載失敗，改用一般縮放：{e}")
        return False


def depth_map(img):
    """Relative nearness in [0, 1] (1 = closest) for a BGR uint8 image, same size as the image."""
    import cv2
    import numpy as np
    import onnxruntime as ort
    global _session
    if _session is None:
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        _session = ort.InferenceSession(str(MODEL_PATH), opts, providers=["CPUExecutionProvider"])
    h, w = img.shape[:2]
    iw = 518
    ih = max(14, int(round(iw * h / w / 14)) * 14)
    x = cv2.resize(img, (iw, ih), interpolation=cv2.INTER_AREA)[:, :, ::-1].astype(np.float32) / 255.0
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    d = _session.run(None, {"pixel_values": x.transpose(2, 0, 1)[None].copy()})[0][0]
    lo, hi = np.percentile(d, 2), np.percentile(d, 98)
    d = np.clip((d - lo) / max(float(hi - lo), 1e-6), 0.0, 1.0).astype(np.float32)
    d = cv2.resize(d, (w, h), interpolation=cv2.INTER_CUBIC)
    k = max(3, int(max(w, h) * 0.015)) | 1      # soften depth edges -> less tearing around objects
    return cv2.GaussianBlur(d, (k, k), 0)


def _sprites(np, cv2, radii):
    out = {}
    for r in radii:
        s = 4 * r + 1
        g = np.zeros((s, s), np.float32)
        cv2.circle(g, (2 * r, 2 * r), r, 1.0, -1, cv2.LINE_AA)
        g = cv2.GaussianBlur(g, (0, 0), r * 0.9)
        out[r] = g / max(float(g.max()), 1e-6)
    return out


def render_shot(img_path: Path, frames: int, out_w: int, out_h: int, fps: int, move: int, out_path: Path,
                seed: int = 0) -> Path:
    """Write `frames` frames of the picture with a depth-parallax camera move and drifting motes to out_path."""
    import cv2
    import numpy as np
    src = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
    cw, ch = int(out_w * MARGIN) // 2 * 2, int(out_h * MARGIN) // 2 * 2
    scale = max(cw / src.shape[1], ch / src.shape[0])
    big = cv2.resize(src, (max(cw, round(src.shape[1] * scale)), max(ch, round(src.shape[0] * scale))),
                     interpolation=cv2.INTER_CUBIC)
    x0, y0 = (big.shape[1] - cw) // 2, int((big.shape[0] - ch) * 0.35)
    canvas = np.ascontiguousarray(big[y0:y0 + ch, x0:x0 + cw])
    depth = depth_map(canvas)
    mx, my = (cw - out_w) / 2, (ch - out_h) / 2
    d = np.ascontiguousarray(depth[int(my):int(my) + out_h, int(mx):int(mx) + out_w])
    rel_x, rel_y = np.meshgrid(np.arange(out_w, dtype=np.float32) - out_w / 2,
                               np.arange(out_h, dtype=np.float32) - out_h / 2)
    near = 0.35 + 0.65 * d                       # how strongly each pixel follows the camera
    lean = d - 0.3                               # lateral parallax: background drifts slightly the other way
    kind = MOVES[move % len(MOVES)]

    rng = random.Random(seed * 7919 + move)
    radii = (2, 3, 5, 7)
    sprites = _sprites(np, cv2, radii)
    motes = []
    for _ in range(MOTES):
        layer = rng.random()
        motes.append({"x": rng.uniform(0, out_w), "y": rng.uniform(0, out_h), "layer": layer,
                      "r": radii[min(3, int(layer * 4))], "vx": rng.uniform(-8, 8),
                      "vy": -(12 + 45 * layer), "b": 0.22 + 0.45 * layer,
                      "f": rng.uniform(0.3, 0.9), "ph": rng.uniform(0, 6.3)})
    tint = np.array([0.80, 0.92, 1.0], np.float32)  # warm white (BGR)

    proc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                             "-s", f"{out_w}x{out_h}", "-r", str(fps), "-i", "-", "-c:v", "libx264",
                             "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(out_path)],
                            stdin=subprocess.PIPE)
    try:
        for i in range(frames):
            p = i / max(frames - 1, 1)
            zoom = {"push_in": ZOOM * p, "pull_out": ZOOM * (1 - p)}.get(kind, ZOOM * 0.35)
            sx = SHIFT * out_w * (2 * p - 1) * {"drift_right": 1, "drift_left": -1}.get(kind, 0.25)
            sy = SHIFT * out_w * (2 * p - 1) * (-0.8 if kind == "rise" else 0.0)
            z = 1.0 + zoom * near
            map_x = cw / 2 + rel_x / z + sx * lean
            map_y = ch / 2 + rel_y / z + sy * lean
            frame = cv2.remap(canvas, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            t = i / fps
            for m in motes:
                x = (m["x"] + m["vx"] * t - sx * (m["layer"] - 0.3) * 1.5) % out_w
                y = (m["y"] + m["vy"] * t) % out_h
                spr = sprites[m["r"]]
                s = spr.shape[0]
                xa, ya = int(x) - s // 2, int(y) - s // 2
                xb, yb = xa + s, ya + s
                if xa < 0 or ya < 0 or xb > out_w or yb > out_h:
                    continue
                glow = m["b"] * (0.65 + 0.35 * math.sin(6.283 * m["f"] * t + m["ph"]))
                add = (spr[:, :, None] * (glow * 255.0) * tint).astype(np.uint8)
                roi = frame[ya:yb, xa:xb]
                cv2.add(roi, add, dst=roi)
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed while writing {out_path.name}")
    return out_path
