#!/usr/bin/env python3
"""胶片库管理：本地 JSON 持久化，供 server.py 与 build_firmware.py 共用。

库文件：film_library.json（与 build_firmware.py 同目录）
结构：
  { "films": { "<key>": { "key", "name", "nick", "short", "de",
                          "fit", "cube", "box": [...] } } }

box 字段扁平化存储图标配色：
  [body_r, body_g, body_b, strip_r, strip_g, strip_b, brand_col, name, name_col, speed, speed_col]
  （name/speed 存字符串，brand_col/name_col/speed_col 存 0=白 1=黑，speed 为空则用 short）
"""
import os, json, time, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
# 库文件固定存在 repo 目录（fit/cube 也都在那里），保证 server 与 build 读写同一份
REPO_DIR = '/Users/macmini/WorkBuddy/2026-10-09-16-58-16/gr3-film-mods'
LIB_PATH = os.environ.get('FILM_LIB_PATH', os.path.join(REPO_DIR, 'film_library.json'))

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
KODAK_RED = (227, 30, 36)


def _load():
    if not os.path.exists(LIB_PATH):
        return {'films': {}}
    try:
        d = json.load(open(LIB_PATH))
    except Exception:
        return {'films': {}}
    d.setdefault('films', {})
    return d


def _save(d):
    json.dump(d, open(LIB_PATH, 'w'), ensure_ascii=False, indent=2)


def list_films():
    return list(_load()['films'].values())


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
    import sys
    sys.path.insert(0, '/Users/macmini/WorkBuddy/2026-10-09-16-58-16/gr3-film-mods')
    import make_icons_custom as mic
    injected = []
    for f in list_films():
        mic.FILM_BOX[f['key']] = film_to_box_tuple(f['box'])
        injected.append(f['key'])
    return injected
