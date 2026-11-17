"""Assembles docs/images/.frames/*.png into the animated tour docs/images/dashboard-tour.gif and shrinks the screenshots
(palette PNGs, same look, about a third of the size). Needs Pillow.

    python3 scripts/frames_to_gif.py [--width 960] [--ms 1800]
"""
import argparse
from pathlib import Path

from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("--width", type=int, default=960)
ap.add_argument("--ms", type=int, default=1800)
opts = ap.parse_args()

images = Path(__file__).resolve().parents[2] / "docs" / "images"
files = sorted((images / ".frames").glob("*.png"))
if not files:
    raise SystemExit("no frames: run `node scripts/showcase.mjs` first")

frames = []
for f in files:
    im = Image.open(f).convert("RGB")
    h = round(im.height * opts.width / im.width)
    frames.append(im.resize((opts.width, h), Image.LANCZOS).quantize(colors=96, method=Image.MEDIANCUT, dither=Image.Dither.NONE))
out = images / "dashboard-tour.gif"
durations = [opts.ms] * len(frames)
durations[0] = opts.ms + 600  # linger on the first screen
frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True, disposal=2)
print(f"{out}: {len(frames)} frames, {out.stat().st_size / 1024:.0f} KB")

before = after = 0
for png in sorted(images.glob("*.png")):
    before += png.stat().st_size
    im = Image.open(png)
    if im.mode != "P":
        im.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(png, optimize=True)
    after += png.stat().st_size
print(f"screenshots: {before / 1024:.0f} KB -> {after / 1024:.0f} KB")
