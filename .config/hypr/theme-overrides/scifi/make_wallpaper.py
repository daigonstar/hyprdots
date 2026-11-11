"""Draws wallpaper.jpg for the Sci-fi HUD theme override: a cyan grid running to a glowing horizon under a ringed planet,
with stars and faint HUD rings. Drawn from scratch (lines, gradients and blur, fixed random seed), so it is original
work under the repo's licence and the same picture every time.

    python3 make_wallpaper.py [WIDTH HEIGHT]"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
CYAN = (0, 229, 255)
VIOLET = (124, 77, 255)


def sky(w, h, horizon):
    """Near black at the top to a deep teal glow at the horizon, then dark below it."""
    img = Image.new("RGB", (1, h))
    px = img.load()
    for y in range(h):
        if y < horizon:
            t = (y / horizon) ** 2.2
            px[0, y] = (int(3 + 6 * t), int(6 + 40 * t), int(16 + 52 * t))
        else:
            t = min(1.0, (y - horizon) / (h - horizon))
            px[0, y] = (int(4 * (1 - t) + 2), int(30 * (1 - t) + 4), int(44 * (1 - t) + 10))
    return img.resize((w, h))


def stars(draw, w, horizon, rng):
    for _ in range(int(w * 0.18)):
        x, y = rng.uniform(0, w), rng.uniform(0, horizon * 0.92)
        b = rng.randint(90, 255)
        r = rng.choice([0.6, 0.8, 1.0, 1.0, 1.6])
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(b, b, min(255, b + 20)))


def planet(layer, w, h, rng):
    """A large dark planet with a lit rim and a thin tilted ring."""
    d = ImageDraw.Draw(layer)
    cx, cy, r = w * 0.72, h * 0.30, h * 0.20
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(8, 22, 40, 255))
    for i in range(14):  # the lit edge, towards the lower left
        rr = r - i * 0.6
        a = int(150 * (1 - i / 14))
        d.arc([cx - rr, cy - rr, cx + rr, cy + rr], 95, 215, fill=(*CYAN, a), width=2)
    ring = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    for k, (scale, alpha) in enumerate(((1.9, 170), (2.05, 90), (2.25, 60))):
        rd.ellipse([cx - r * scale, cy - r * scale * 0.22, cx + r * scale, cy + r * scale * 0.22],
                   outline=(*CYAN, alpha), width=3 - k)
    ring = ring.rotate(-14, center=(cx, cy), resample=Image.BICUBIC)
    # the ring passes behind the planet at the top: hide that half where it crosses the disc
    mask = Image.new("L", layer.size, 255)
    md = ImageDraw.Draw(mask)
    md.pieslice([cx - r, cy - r, cx + r, cy + r], 180, 360, fill=0)
    ring.putalpha(ImageChops.multiply(ring.getchannel("A"), mask))
    layer.alpha_composite(ring)


def grid(layer, w, h, horizon):
    """A floor of cyan lines running to a vanishing point on the horizon, fading with distance."""
    d = ImageDraw.Draw(layer)
    vx = w / 2
    for i in range(-40, 41):
        x_far = vx + i * w * 0.012
        x_near = vx + i * w * 0.11
        d.line([(x_far, horizon), (x_near, h)], fill=(*CYAN, 70), width=2)
    for k in range(1, 40):
        t = (k / 40) ** 2.4
        y = horizon + (h - horizon) * t
        a = int(25 + 150 * t)
        d.line([(0, y), (w, y)], fill=(*CYAN, a), width=2 if t > 0.3 else 1)


def hud(layer, w, h, rng):
    """Faint rings and tick marks, like a targeting display, around the planet and in a corner."""
    d = ImageDraw.Draw(layer)
    for cx, cy, r in ((w * 0.72, h * 0.30, h * 0.30), (w * 0.14, h * 0.22, h * 0.10)):
        for rr, a, span in ((r, 60, (200, 340)), (r * 1.12, 35, (20, 160)), (r * 0.8, 30, (250, 300))):
            d.arc([cx - rr, cy - rr, cx + rr, cy + rr], span[0], span[1], fill=(*CYAN, a), width=2)
        for deg in range(0, 360, 10):
            a = math.radians(deg)
            inner = r * (1.03 if deg % 30 else 0.98)
            d.line([(cx + math.cos(a) * inner, cy + math.sin(a) * inner),
                    (cx + math.cos(a) * r * 1.07, cy + math.sin(a) * r * 1.07)], fill=(*CYAN, 45), width=1)


def draw(w=2560, h=1440):
    rng = random.Random(2049)
    s = 2  # drawn at twice the size and shrunk: smooth lines
    W, H = w * s, h * s
    horizon = int(H * 0.60)
    base = sky(W, H, horizon).convert("RGBA")
    stars(ImageDraw.Draw(base), W, horizon, rng)
    lines = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    planet(lines, W, H, rng)
    hud(lines, W, H, rng)
    floor = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grid(floor, W, H, horizon)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))  # the horizon's light
    ImageDraw.Draw(glow).rectangle([0, horizon - 6, W, horizon + 6], fill=(*CYAN, 230))
    glow = glow.filter(ImageFilter.GaussianBlur(40 * s))
    for layer in (floor, lines):
        base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(6 * s)))  # each line's soft glow
        base.alpha_composite(layer)
    base.alpha_composite(glow)
    ImageDraw.Draw(base).line([(0, horizon), (W, horizon)], fill=(180, 250, 255, 255), width=2 * s)
    return base.convert("RGB").resize((w, h), Image.LANCZOS)


if __name__ == "__main__":
    size = tuple(int(a) for a in sys.argv[1:3]) if len(sys.argv) >= 3 else (2560, 1440)
    draw(*size).save(HERE / "wallpaper.jpg", quality=92, optimize=True)
