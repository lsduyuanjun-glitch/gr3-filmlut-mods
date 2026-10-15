#!/usr/bin/env python3
"""英泽君 4 胶片推荐基底 -> CUBE 直读 -> v12 三阶段拟合 -> ΔE 对照。

对每个推荐基底跑 run_film_from_cube，得到 lab_fit 后的 colorchecker ΔE，
并与本地端旧版 duccio5207/duccio5219 的 lab ΔE 对比。
"""
import sys, os, json
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)  # gr3-film-mods
sys.path.insert(0, REPO)

import film_pipeline

BASE = '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/'

# 推荐基底（一胶片一个）
RECOMMEND = [
    ('portra400_yingzejun', 'Kodak Portra 400', '英泽君的真彩色Portra400 Liit/原 RCP400 -S.cube'),
    ('5207_yingzejun',      'Kodak 5207',       '英泽君的Kodak5207 Liit版/原 5207 - S.cube'),
    ('5219_yingzejun',      'Kodak 5219',       '英泽君柯达5219 Liit版/标 5219 - S.cube'),
    ('ektar100_yingzejun',  'Kodak Ektar 100',  '英泽君柯达Ektar100V2 Liit版/原 Ektar100 - S.cube'),
]

# 本地端旧版（对照）
OLD = [
    ('duccio5207_old', '本地旧版 5207', REPO + '/work/films_v11/fits/duccio5207_standardpro_b4n3_lab.json'),
    ('duccio5219_old', '本地旧版 5219', REPO + '/work/films_v11/fits/duccio5219_standardpro_b4n3_lab.json'),
]

CUBE_DIR = os.path.join(REPO, 'work', 'yingzejun_cubes')

def main():
    os.makedirs(CUBE_DIR, exist_ok=True)
    results = []

    print('=' * 70)
    print('跑 4 个推荐基底（CUBE 直读 -> 三阶段拟合）')
    print('=' * 70)
    for key, name, rel in RECOMMEND:
        src = BASE + rel
        if not os.path.exists(src):
            print(f'[跳过] {key}: 文件不存在 {src}')
            continue
        print(f'\n>>> {name} ({key})')
        box = ('#888888', '#e31e24', '#fcfcfc', name, '#141210', key.upper(), '#fcfcfc')
        try:
            r = film_pipeline.run_film_from_cube(
                src, key, name, box, CUBE_DIR, boost=4, neutral=3)
            results.append((key, name, r['de'], 'yingzejun'))
            print(f'    ΔE = {r["de"]}')
            print(f'    灰轴: {[g["rb"] for g in r["gray"]]}')
        except Exception as e:
            print(f'    [失败] {key}: {e}')
            results.append((key, name, None, 'yingzejun'))

    print('\n' + '=' * 70)
    print('本地端旧版对照 ΔE')
    print('=' * 70)
    for key, name, labpath in OLD:
        if not os.path.exists(labpath):
            print(f'[跳过] {key}: 文件不存在')
            continue
        d = json.load(open(labpath))
        de = d.get('lab_fit', {}).get('after', {}).get('colorchecker', '?')
        results.append((key, name, de, 'old'))
        print(f'    {name}: ΔE = {de}')

    print('\n' + '=' * 70)
    print('汇总对照表')
    print('=' * 70)
    print(f'{"胶片":<24}{"来源":<12}{"ΔE":<10}')
    print('-' * 46)
    for key, name, de, src in results:
        de_s = f'{de}' if de is not None else '失败'
        print(f'{name:<24}{src:<12}{de_s:<10}')

    # 保存结果
    out = os.path.join(CUBE_DIR, 'fit_results.json')
    json.dump([{'key': k, 'name': n, 'de': d, 'source': s}
               for k, n, d, s in results], open(out, 'w'), ensure_ascii=False, indent=2)
    print(f'\n结果已存: {out}')

if __name__ == '__main__':
    main()
