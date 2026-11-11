"""Draws wallpaper.jpg for the Mac style theme override: broad, smooth bands of colour sweeping across a dusk
gradient. Drawn from scratch (gradients, curves and blur), so it is original work under the repo's licence and not a
copy of any Apple wallpaper.

    python3 make_wallpaper.py [WIDTH HEIGHT]"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def diagonal(size, c0, c1, c2):
    """A gradient from the top left (c0) through the middle (c1) to the bottom right (c2)."""
    w, h = size
    small = Image.new("RGB", (64, 36))
    px = small.load()
    for y in range(36):
        for x in range(64):
            t = (x / 63 * 0.6 + y / 35 * 0.4)
            px[x, y] = lerp(c0, c1, t / 0.5) if t < 0.5 else lerp(c1, c2, (t - 0.5) / 0.5)
    return small.resize((w, h), Image.BICUBIC)


def wave(w, h, base, amp, freq, phase, tilt):
    """y of a band's edge along the width: a slow wave on a gentle slope."""
    return [(x, base * h + tilt * h * (x / w - 0.5) + amp * h * math.sin(freq * math.pi * x / w + phase))
            for x in range(0, w + 16, 16)]


def band(img, top, bottom, colours, glow):
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(top + bottom[::-1], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(h * 0.004))
    fill = diagonal((w, h), *colours)
    img.paste(fill, (0, 0), mask)
    # a soft light along the band's upper edge, and a shadow under it, so the bands seem to fold over each other
    edge = Image.new("L", (w, h), 0)
    ImageDraw.Draw(edge).line(top, fill=glow, width=max(2, h // 90))
    edge = edge.filter(ImageFilter.GaussianBlur(h * 0.012))
    img.paste(Image.new("RGB", (w, h), (255, 255, 255)), (0, 0), ImageChops.multiply(edge, mask))
    shade = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shade).line([(x, y + h * 0.02) for x, y in bottom], fill=110, width=h // 40)
    shade = shade.filter(ImageFilter.GaussianBlur(h * 0.03))
    img.paste(Image.new("RGB", (w, h), (10, 8, 40)), (0, 0), ImageChops.multiply(shade, ImageChops.invert(mask)))


def draw(w=2560, h=1440):
    img = diagonal((w, h), (24, 22, 78), (70, 40, 140), (230, 120, 110))
    bands = [  # (top edge, bottom edge, colours, glow)
        (wave(w, h, 0.30, 0.06, 1.2, 0.3, -0.35), wave(w, h, 0.52, 0.05, 1.1, 0.9, -0.30),
         ((40, 70, 200), (90, 80, 220), (150, 90, 210)), 90),
        (wave(w, h, 0.48, 0.07, 1.0, 1.6, -0.25), wave(w, h, 0.70, 0.06, 1.3, 2.0, -0.20),
         ((60, 150, 240), (110, 110, 235), (200, 100, 200)), 110),
        (wave(w, h, 0.66, 0.06, 0.9, 2.6, -0.18), wave(w, h, 0.90, 0.05, 1.2, 3.1, -0.10),
         ((120, 90, 220), (220, 100, 170), (255, 150, 110)), 120),
        (wave(w, h, 0.86, 0.05, 1.1, 3.8, -0.12), wave(w, h, 1.15, 0.02, 1.0, 4.0, -0.05),
         ((200, 90, 170), (255, 130, 120), (255, 190, 120)), 120),
    ]
    for top, bottom, colours, glow in bands:
        band(img, top, bottom, colours, glow)
    grain = Image.effect_noise((w // 2, h // 2), 10).resize((w, h))
    return Image.blend(img, Image.merge("RGB", (grain,) * 3), 0.025)


if __name__ == "__main__":
    size = tuple(int(a) for a in sys.argv[1:3]) if len(sys.argv) >= 3 else (2560, 1440)
    draw(*size).save(HERE / "wallpaper.jpg", quality=90, optimize=True)
    print(HERE / "wallpaper.jpg")
