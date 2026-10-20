#!/usr/bin/env python3
"""胶片库管理：本地 JSON 持久化，供 server.py 与 build_firmware.py 共用。

★ 打包版关键差异：库文件与自建胶片的 fit/cube 必须写到「用户可写目录」，
  不能写在只读的 app 包内部（macOS 上 .app 内部不可写）。
  位置由 paths.py 统一决定：~/Library/Application Support/GR3FilmTool/

结构：
  { "films": { "<key>": { "key", "name", "nick", "short", "de",
                          "fit", "cube", "box": [...] } } }

box 字段扁平化存储图标配色：
  [body_r, body_g, body_b, strip_r, strip_g, strip_b, brand_col, name, name_col, speed, speed_col]
  （name/speed 存字符串，brand_col/name_col/speed_col 存 0=白 1=黑，speed 为空则用 short）
"""
import os
import sys
import json
import time
import hashlib

# paths.py 在 webtool/（开发环境）；打包环境下所有 .py 同目录，这步无害
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'webtool'))
try:
    import paths  # noqa: E402
    LIB_PATH = os.environ.get('FILM_LIB_PATH', paths.LIB_PATH)
    REPO_DIR = paths.RESOURCE_DIR
except Exception:                                    # 极端兜底：paths 不可用时退回归属本目录
    HERE = os.path.dirname(os.path.abspath(__file__))
    REPO_DIR = HERE
    LIB_PATH = os.environ.get('FILM_LIB_PATH', os.path.join(HERE, 'film_library.json'))

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
KODAK_RED = (227, 30, 36)

# ★ 预设款（随工具出货的 Duccio 自制胶片）：前端不标 ★ /（自建），只显示名字。
#   用户自己上传的（CUBE/XMP）才显示（自建）标记。
PRESET_KEYS = {'duccio_b10575ad', 'duccio_752a2252'}


def _load():
    if not os.path.exists(LIB_PATH):
        return {'films': {}}
    try:
        d = json.load(open(LIB_PATH, encoding='utf-8'))
    except Exception:
        return {'films': {}}
    d.setdefault('films', {})
    return d


def _save(d):
    os.makedirs(os.path.dirname(LIB_PATH), exist_ok=True)
    json.dump(d, open(LIB_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


def list_films():
    films = list(_load()['films'].values())
    for f in films:
        if f.get('key') in PRESET_KEYS:
            f['preset'] = True      # 前端据此决定是否标（自建）
    return films


def get_film(key):
    return _load()['films'].get(key)


def _key_of(name):
    h = hashlib.md5(f'{name}-{time.time()}'.encode()).hexdigest()[:8]
    return f'duccio_{h}'


def add_film(pipeline_result, nick=None, short=None):
    """把 run_film 的结果写入库。pipeline_result 含 key/name/de/fit/cube/box。"""
    d = _load()
    key = pipeline_result['key']
    name = pipeline_result['name']
    box = pipeline_result['box']  # (body, strip, brand_col, name, name_col, speed, speed_col)

    # 展平 box -> 可 JSON 存储
    body, strip, brand_col, box_name, name_col, speed, speed_col = box
    flat_box = [
        list(body), list(strip),
        0 if brand_col == WHITE else 1,
        box_name,
        0 if name_col == WHITE else 1,
        speed if speed else short or name,
        0 if speed_col == WHITE else 1,
    ]

    d['films'][key] = {
        'key': key,
        'name': name,
        'nick': nick or name,
        'short': short or (speed if isinstance(speed, str) else name),
        'de': pipeline_result['de'],
        'fit': pipeline_result['fit'],
        'cube': pipeline_result['cube'],
        'box': flat_box,
        'gray': pipeline_result.get('gray', []),
        'hue_q10': pipeline_result.get('hue_q10', []),
    }
    _save(d)
    return d['films'][key]


def rename_film(key, new_name, new_nick=None, new_short=None):
    d = _load()
    if key not in d['films']:
        return None
    f = d['films'][key]
    f['name'] = new_name
    if new_nick is not None:
        f['nick'] = new_nick
    if new_short is not None:
        f['short'] = new_short
    _save(d)
    return f


def delete_film(key):
    d = _load()
    if key not in d['films']:
        return False
    del d['films'][key]
    _save(d)
    return True


def set_film_icon(key, png_b64):
    """把自建胶片的机内图标（40×40 PNG 的 base64）写进库的 icon 字段。返回是否成功。"""
    d = _load()
    if key not in d['films']:
        return False
    d['films'][key]['icon'] = png_b64
    _save(d)
    return True


def film_to_box_tuple(flat_box):
    """把库里的 flat_box 还原成 make_icons_custom.FILM_BOX 元组。"""
    body = tuple(flat_box[0])
    strip = tuple(flat_box[1])
    brand_col = WHITE if flat_box[2] == 0 else BLACK
    name = flat_box[3]
    name_col = WHITE if flat_box[4] == 0 else BLACK
    speed = flat_box[5]
    speed_col = WHITE if flat_box[6] == 0 else BLACK
    return (body, strip, brand_col, name, name_col, speed, speed_col)


def inject_into_filmbox():
    """把库里的胶片动态注入 make_icons_custom.FILM_BOX，返回注入的 key 列表。"""
    sys.path.insert(0, REPO_DIR)
    import make_icons_custom as mic
    injected = []
    for f in list_films():
        mic.FILM_BOX[f['key']] = film_to_box_tuple(f['box'])
        injected.append(f['key'])
    return injected
