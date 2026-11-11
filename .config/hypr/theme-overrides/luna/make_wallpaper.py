"""Draws wallpaper.jpg for the XP style theme override: a rolling green hill under a blue sky with soft clouds.

Everything here is drawn from scratch (gradients, curves and blurred shapes), so the picture is original work under the
repo's licence. It is not a copy of any photo. Run it again to make a different size:

    python3 make_wallpaper.py [WIDTH HEIGHT]"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def vertical(size, stops):
    """A top-to-bottom gradient through (position 0..1, rgb) stops."""
    w, h = size
    strip = Image.new("RGB", (1, h))
    px = strip.load()
    for y in range(h):
        t = y / max(1, h - 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= t <= p1:
                px[0, y] = lerp(c0, c1, (t - p0) / max(1e-6, p1 - p0))
                break
    return strip.resize((w, h))


def hill_curve(w, h, base, peak, width, ripple):
    """Top edge of a hill: one broad rounded rise centred at x = peak (0..1) on a baseline, with a faint ripple."""
    pts = []
    for x in range(0, w + 8, 8):
        t = x / w
        rise = math.exp(-((t - peak) / width) ** 2)
        y = base - rise * h * 0.16 + ripple * h * math.sin(t * 7.3 + peak * 5)
        pts.append((x, y))
    return pts


def cloud(canvas, cx, cy, scale, rnd):
    """A cumulus: many overlapping soft puffs, flatter underneath."""
    layer = Image.new("L", canvas.size, 0)
    shade = Image.new("L", canvas.size, 0)
    d, ds = ImageDraw.Draw(layer), ImageDraw.Draw(shade)
    for i in range(40):
        spread = 1.0 - i / 60  # later puffs sit nearer the middle and higher, so the top billows
        dx = rnd.gauss(0, 0.9) * scale * 1.5 * spread
        dy = -abs(rnd.gauss(0, 0.5)) * scale * (1.2 - spread)
        r = scale * rnd.uniform(0.25, 0.55) * (1.3 - spread * 0.5)
        box = (cx + dx - r, cy + dy - r, cx + dx + r, cy + dy + r)
        d.ellipse(box, fill=255)
        ds.ellipse((box[0], box[1] + r * 0.9, box[2], box[3] + r * 0.4), fill=90)
    flat = cy + scale * 0.3  # flat underside
    d.rectangle((0, flat, canvas.size[0], canvas.size[1]), fill=0)
    ds.rectangle((0, flat, canvas.size[0], canvas.size[1]), fill=0)
    layer = layer.filter(ImageFilter.GaussianBlur(scale * 0.07))
    shade = Image.composite(shade, Image.new("L", canvas.size, 0), layer).filter(ImageFilter.GaussianBlur(scale * 0.12))
    canvas.paste(Image.new("RGB", canvas.size, (250, 252, 255)), (0, 0), layer.point(lambda v: v * 0.92))
    canvas.paste(Image.new("RGB", canvas.size, (170, 190, 220)), (0, 0), shade)


def draw(w=2560, h=1440, seed=7):
    rnd = random.Random(seed)
    img = vertical((w, h), [(0.0, (18, 72, 190)), (0.35, (52, 120, 222)), (0.62, (128, 180, 238)), (1.0, (196, 224, 248))])
    for cx, cy, size in ((0.16, 0.16, 0.075), (0.47, 0.09, 0.05), (0.78, 0.22, 0.085), (0.33, 0.37, 0.04),
                         (0.93, 0.42, 0.035), (0.6, 0.44, 0.03)):
        cloud(img, cx * w, cy * h, size * h, rnd)

    # far hill: hazy, bluer green
    far = hill_curve(w, h, h * 0.74, 0.12, 0.35, 0.006)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(far + [(w, h), (0, h)], fill=255)
    img.paste(vertical((w, h), [(0.0, (120, 170, 110)), (0.7, (95, 150, 80)), (1.0, (70, 125, 60))]), (0, 0),
              mask.filter(ImageFilter.GaussianBlur(3)))

    # near hill: one broad rise, lit from the upper left
    near = hill_curve(w, h, h * 0.86, 0.58, 0.42, 0.004)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(near + [(w, h), (0, h)], fill=255)
    grass = vertical((w, h), [(0.0, (160, 215, 70)), (0.6, (115, 190, 40)), (0.82, (70, 150, 25)), (1.0, (40, 110, 15))])
    light = Image.new("L", (w, h), 0)  # a broad sunlit band along the crest
    ImageDraw.Draw(light).polygon([(x, y + h * 0.015) for x, y in near] + [(w, h * 0.95), (0, h * 0.95)], fill=110)
    light = light.filter(ImageFilter.GaussianBlur(h * 0.05))
    grass.paste(Image.new("RGB", (w, h), (205, 235, 120)), (0, 0), light)
    texture = Image.effect_noise((w // 4, h // 4), 18).resize((w, h)).filter(ImageFilter.GaussianBlur(1.2))
    grass = Image.composite(grass, Image.blend(grass, Image.merge("RGB", (texture,) * 3), 0.06), Image.new("L", (w, h), 200))
    img.paste(grass, (0, 0), mask.filter(ImageFilter.GaussianBlur(1.5)))
    return img


if __name__ == "__main__":
    size = tuple(int(a) for a in sys.argv[1:3]) if len(sys.argv) >= 3 else (2560, 1440)
    draw(*size).save(HERE / "wallpaper.jpg", quality=90, optimize=True)
    print(HERE / "wallpaper.jpg")
