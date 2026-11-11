"""Draws wallpaper.jpg for the Game UI theme override: a pixel-art dusk over mountains, hills, pines and a still lake,
drawn at 320x180 and scaled up with hard pixel edges. Drawn from scratch with a fixed random seed, so it is original
work under the repo's licence and the same picture every time.

    python3 make_wallpaper.py [WIDTH HEIGHT]"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
W, H = 320, 180
HORIZON = 118  # the lake's far shore

# the sky from the top down: deep night blue to a warm glow at the horizon, in flat bands like an old game's palette
SKY = [(14, 18, 62), (22, 26, 86), (34, 34, 110), (52, 42, 128), (78, 52, 140), (112, 62, 142), (150, 76, 132),
       (190, 98, 118), (224, 128, 104), (246, 168, 102)]
FAR = (58, 50, 120)  # far mountains
FAR_SNOW = (164, 150, 200)
NEAR = (34, 34, 88)  # near mountains
HILL = [(28, 70, 74), (22, 56, 64), (16, 42, 52)]  # hills, light to dark
PINE = (10, 28, 40)
WATER = (20, 24, 70)


def dithered_sky(px, rng):
    """Flat bands with a checkerboard blend where two meet, as old games did with few colours."""
    band_h = HORIZON / len(SKY)
    for y in range(HORIZON):
        pos = y / band_h
        i = min(int(pos), len(SKY) - 1)
        frac = pos - i
        for x in range(W):
            use_next = frac > 0.6 and (x + y) % 2 == 0 and i + 1 < len(SKY)
            px[x, y] = SKY[i + 1] if use_next else SKY[i]


def stars(px, rng):
    for _ in range(70):
        x, y = rng.randrange(W), rng.randrange(int(HORIZON * 0.5))
        px[x, y] = rng.choice([(255, 255, 255), (200, 210, 255), (255, 236, 190)])
    for x, y in ((46, 14), (250, 22), (192, 9)):  # a few bright ones with a cross
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            px[x + dx, y + dy] = (255, 255, 255) if (dx, dy) == (0, 0) else (170, 180, 240)


def moon(px):
    cx, cy, r = 262, 34, 11
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            d = math.hypot(x - cx, y - cy)
            if d <= r:
                shade = (250, 240, 210) if math.hypot(x - cx + 5, y - cy + 3) > 6 else (232, 220, 190)
                px[x, y] = shade
            elif d <= r + 2 and (x + y) % 2 == 0:
                px[x, y] = SKY[1]  # a dithered halo
    for x, y in ((258, 30), (259, 30), (266, 37), (263, 40), (264, 40)):  # craters
        px[x, y] = (214, 200, 170)


def ridge(rng, base, height, roughness, peaks):
    """y of a mountain ridge for every x: a few peaks with stepped, jagged slopes."""
    tops = [(rng.uniform(0, W), rng.uniform(0.6, 1.0) * height) for _ in range(peaks)]
    ys = []
    for x in range(W):
        h = max(t * max(0.0, 1 - abs(x - px_) / (W / peaks * 0.9)) for px_, t in tops)
        h += rng.uniform(-roughness, roughness)
        ys.append(int(base - h))
    return ys


def fill_below(px, ys, colour, bottom=HORIZON):
    for x, top in enumerate(ys):
        for y in range(max(0, top), bottom):
            px[x, y] = colour


def mountains(px, rng):
    far = ridge(rng, HORIZON, 58, 1.2, 5)
    fill_below(px, far, FAR)
    for x, top in enumerate(far):  # snow on the highest
        if top < HORIZON - 44:
            for y in range(top, top + 3 + (x % 3 == 0)):
                px[x, y] = FAR_SNOW
    near = ridge(rng, HORIZON, 34, 1.0, 7)
    fill_below(px, near, NEAR)


def hills(px, rng):
    for i, (base, amp, freq, phase) in enumerate(((HORIZON + 2, 7, 2.2, 0.4), (HORIZON + 6, 6, 3.1, 2.0),
                                                   (HORIZON + 10, 5, 4.0, 4.1))):
        ys = [int(base - amp - amp * math.sin(freq * math.pi * x / W + phase)) for x in range(W)]
        fill_below(px, ys, HILL[i], bottom=HORIZON + 14)
        if i == 2:
            return ys


def pine(px, x, base, height):
    for row in range(height):
        half = max(0, (row * 3) // height + (row % 3 == 2))
        for dx in range(-half, half + 1):
            y = base - height + row
            if 0 <= x + dx < W and 0 <= y < H:
                px[x + dx, y] = PINE
    px[x, base] = PINE


def lake(px, img):
    """Below the shore: the sky and land mirrored, darkened, with broken lines of light."""
    shore = HORIZON + 14
    for y in range(shore, H):
        src = shore - (y - shore) - 1
        for x in range(W):
            r, g, b = px[x, max(0, src)]
            px[x, y] = (int(r * 0.45 + WATER[0] * 0.55), int(g * 0.45 + WATER[1] * 0.55), int(b * 0.45 + WATER[2] * 0.55))
    rng = random.Random(7)
    for _ in range(120):  # ripples
        y = rng.randrange(shore + 1, H)
        x = rng.randrange(W - 6)
        for dx in range(rng.randrange(2, 7)):
            r, g, b = px[x + dx, y]
            px[x + dx, y] = (min(255, r + 26), min(255, g + 26), min(255, b + 34))
    for y in range(shore + 2, H, 3):  # the moon's path on the water
        width = 2 + (y - shore) // 6
        for dx in range(-width, width + 1):
            if (dx + y) % 3:
                px[262 + dx, y] = (236, 222, 180)


def draw(w=2560, h=1440):
    rng = random.Random(1987)
    img = Image.new("RGB", (W, H))
    px = img.load()
    dithered_sky(px, rng)
    stars(px, rng)
    moon(px)
    mountains(px, rng)
    front = hills(px, rng)
    for x in list(range(4, 120, 7)) + list(range(206, 316, 9)):
        pine(px, x + rng.randrange(-2, 3), front[min(x, W - 1)] + 3, rng.randrange(7, 13))
    lake(px, img)
    big = img.resize((W * math.ceil(w / W), H * math.ceil(h / H)), Image.NEAREST)
    return big.crop((0, 0, w, h)) if big.size != (w, h) else big


if __name__ == "__main__":
    size = tuple(int(a) for a in sys.argv[1:3]) if len(sys.argv) >= 3 else (2560, 1440)
    draw(*size).save(HERE / "wallpaper.jpg", quality=95, subsampling=0, optimize=True)
