"""Film box icons v5 (40x40 RGBA) — 紧凑胶卷盒风格.

参考：GR3 真机菜单里的胶卷盒小图标（Portra/5207/Gold 200/C200/Provia）。
感觉要点（对照参考图）：
  - 无挂孔耳朵，盒子撑满图标，圆角小
  - 居中三行文字：小品牌字 / 片名 / 大号速度数字
  - 饱和纯色盒身，浅色盒用黑字、深色盒用白字
  - 顶部一条窄的品牌色块（Kodak 红 / Fuji 绿），像真盒上的色标条

Usage:
  python make_icons_custom.py out.png
  (library) patch_icons_box(img, {mode: {'film': 'portra400', 'text': None}})
"""
import numpy as np
from PIL import Image as PImage, ImageDraw, ImageFont
from make_icons import put_icon, descriptor, ICON_ID

FONT = '/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf'
S = 12
BOX = 40

KODAK_YELLOW = (247, 181, 0)
KODAK_RED    = (227, 30, 36)
WHITE        = (252, 252, 252)
BLACK        = (20, 18, 16)

# film -> (body, brand-strip colour, brand text col, name, name col, speed, speed col)
FILM_BOX = {
    'portra400':   (KODAK_YELLOW,  KODAK_RED, WHITE, 'PORTRA',  BLACK, '400',  BLACK),
    'gold200':     ((243, 148, 0), KODAK_RED, WHITE, 'GOLD',    BLACK, '200',  BLACK),
    'ektar100':    ((204, 28, 32), KODAK_RED, WHITE, 'EKTAR',   WHITE, '100',  WHITE),
    'pro400h':     ((24, 106, 74), (11, 138, 69), WHITE, 'PRO', WHITE, '400H', WHITE),
    'vision3250d': ((28, 92, 176), KODAK_RED, WHITE, 'VISION3', WHITE, '250D', WHITE),
    # Duccio 专属胶片（自研拟合，v12：5219 dE 1.73 / 5207 dE 1.55）— Kodak Vision3 电影胶片盒风格
    'duccio5219':  ((16, 34, 68),  KODAK_RED, WHITE, 'VISION3', WHITE, '5219', (247, 181, 0)),
    'duccio5207':  ((238, 196, 60), KODAK_RED, BLACK, 'VISION3', BLACK, '5207', BLACK),
}


def _text(d, s, cap_top, cap_h, fill, max_w, cx=BOX * S // 2):
    size = int(cap_h * S * 1.22)
    font = ImageFont.truetype(FONT, size)
    l, t, r, b = d.textbbox((0, 0), s, font=font)
    if r - l > max_w * S:
        tmp = PImage.new('L', (r - l + 8, b - t + 8), 0)
        ImageDraw.Draw(tmp).text((-l + 4, -t + 4), s, font=font, fill=255)
        tmp = tmp.resize((max_w * S, max(1, int(tmp.height * max_w * S / (r - l)))), PImage.LANCZOS)
        d.bitmap((cx - tmp.width // 2, cap_top * S - t), tmp, fill=fill)
        return
    d.text((cx - (r - l) // 2 - l, cap_top * S - t), s, font=font, fill=fill)


def render_box(body, strip_col, brand_col, name, name_col, speed, speed_col):
    big = PImage.new('RGBA', (BOX * S, BOX * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    # 盒身撑满 + 顶部窄品牌色条（像真盒上的色标条）
    d.rounded_rectangle([0, 0, BOX * S, BOX * S], radius=3 * S, fill=body + (255,))
    d.rectangle([0, 0, BOX * S, 4 * S], fill=strip_col + (255,))
    # 三行居中文字：品牌小字 / 片名 / 大号速度
    _text(d, 'Kodak', 5, 5, brand_col, 36)
    _text(d, name, 12, 6, name_col, 38)
    _text(d, speed, 21, 13, speed_col, 38)
    img = big.resize((BOX, BOX), PImage.LANCZOS)
    a = np.asarray(img).copy()
    # 顶部色条盖回圆角外的透明区
    for x in range(BOX):
        for y in range(2):
            if a[y, x, 3] == 0:
                a[y, x, :] = 0
    # 圆角
    for y in range(3):
        for x in range(3 - y):
            for py, px in ((y, x), (y, 39 - x), (39 - y, x), (39 - y, 39 - x)):
                a[py, px, 3] = 0
    return a


def patch_icons_box(img, box_specs):
    done = {}
    for mode, spec in box_specs.items():
        film = spec['film']
        body, strip, brand_col, name, name_col, speed, speed_col = FILM_BOX[film]
        if spec.get('text'):
            speed = spec['text']
        icon_id = ICON_ID[mode]
        assert descriptor(img, icon_id)[:2] == (BOX, BOX)
        put_icon(img, icon_id, render_box(body, strip, brand_col, name, name_col, speed, speed_col))
        done[mode] = (hex(icon_id), speed)
    return done


def preview(path, films=('portra400', 'gold200', 'ektar100', 'pro400h', 'vision3250d'), scale=6):
    tiles = [render_box(*FILM_BOX[f]) for f in films]
    im = np.concatenate(tiles, 1)
    PImage.fromarray(im, 'RGBA').resize((im.shape[1] * scale, im.shape[0] * scale), PImage.NEAREST).save(path)


if __name__ == '__main__':
    import sys
    preview(sys.argv[1] if len(sys.argv) > 1 else 'box_preview.png')
