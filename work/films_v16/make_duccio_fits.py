#!/usr/bin/env python3
"""为 Duccio 的 6 个胶片生成 v16 fit（v11 fit + 中性 hue_q10）。

v16 管线（make_slots16.patch_ma）要求每个 fit 文件含 'hue_q10'（12×3×3，每行和 1024）。
这里用中性恒等矩阵（不做色相偏移）作为默认，让胶片能被 v16 识别并启用 MultiAxial 能力。
后续如需按胶片特性做 12 分区色相偏移，可单独拟合替换（依赖 GR4-LUTSmith）。

源 v11 fit（work/films_v11/fits/）→ 目标 v16 fit（work/films_v16/fits/duccio/）。
"""
import os, json

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'films_v11', 'fits')
DST = os.path.join(HERE, 'fits', 'duccio')
os.makedirs(DST, exist_ok=True)

# 中性 12 分区色相：12 个 3×3 单位阵 ×1024（每行和 1024，无任何色相偏移）
NEUTRAL_HUE_Q10 = [[[1024, 0, 0], [0, 1024, 0], [0, 0, 1024]] for _ in range(12)]

# key -> 源 v11 fit 文件名
FILMS = {
    'duccio5219': 'duccio5219_standardpro_b4n3_lab.json',
    'duccio5207': 'duccio5207_standardpro_b4n3_lab.json',
    'portra400':   'portra400_yingzejun_b4n3_lab.json',
    '5207':        '5207_yingzejun_b4n3_lab.json',
    '5219':        '5219_yingzejun_b4n3_lab.json',
    'ektar100':    'ektar100_yingzejun_b4n3_lab.json',
}

for key, fname in FILMS.items():
    src = os.path.join(SRC, fname)
    if not os.path.exists(src):
        print(f'[跳过] {key}: 源文件不存在 {fname}')
        continue
    d = json.load(open(src))
    # 注入中性 hue_q10（12 分区色相，默认中性）
    d['hue_q10'] = NEUTRAL_HUE_Q10
    # 记录来源（便于追溯）
    d['v16'] = {'source': fname, 'hue': 'neutral'}
    out = os.path.join(DST, f'{key}.json')
    json.dump(d, open(out, 'w'), ensure_ascii=False)
    de = d.get('lab_fit', {}).get('after', {}).get('colorchecker', 0)
    print(f'[OK] {key:12s} <- {fname:40s} ΔE={de}  hue_q10=中性(12分区)')

print('\n完成。目标目录:', DST)
