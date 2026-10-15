#!/usr/bin/env python3
"""校准版 4 胶片 -> CUBE 直读 -> 拟合 -> ΔE（验证校准没破坏拟合精度）。"""
import sys, os, json
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
import film_pipeline

CAL_DIR = os.path.join(REPO, 'work', 'yingzejun_cubes', 'calibrated')

FILMS = [
    ('portra400_cal', 'Portra 400 校准版', 'Portra400_calibrated.cube'),
    ('5207_cal',      '5207 校准版',      '5207_calibrated.cube'),
    ('5219_cal',      '5219 校准版',      '5219_calibrated.cube'),
    ('ektar100_cal',  'Ektar 100 校准版', 'Ektar100_calibrated.cube'),
]

# 对照：未校准的英泽君原版 ΔE（上一轮已跑出）
ORIG_DE = {
    'Portra400': 1.61, '5207': 1.66, '5219': 1.81, 'Ektar100': 1.89,
}

CUBE_DIR = os.path.join(REPO, 'work', 'yingzejun_cubes', 'fit_cal')

def main():
    os.makedirs(CUBE_DIR, exist_ok=True)
    print('=' * 66)
    print('校准版 4 胶片拟合（对照原版 ΔE）')
    print('=' * 66)
    results = []
    for key, name, fname in FILMS:
        src = os.path.join(CAL_DIR, fname)
        if not os.path.exists(src):
            print(f'[跳过] {key}: 不存在'); continue
        box = ('#888888', '#e31e24', '#fcfcfc', name, '#141210', key.upper(), '#fcfcfc')
        try:
            r = film_pipeline.run_film_from_cube(src, key, name, box, CUBE_DIR, boost=4, neutral=3)
            results.append((key, name, r['de']))
            print(f'  {name:<22} ΔE = {r["de"]}')
        except Exception as e:
            print(f'  [失败] {key}: {e}')

    print('\n' + '=' * 66)
    print('原版 vs 校准版 ΔE 对照')
    print('=' * 66)
    print(f'{"胶片":<22}{"原版ΔE":<10}{"校准版ΔE":<10}{"变化"}')
    print('-' * 52)
    for key, name, de in results:
        base = key.replace('_cal', '').replace('portra400', 'Portra400').replace('5207', '5207').replace('5219', '5219').replace('ektar100', 'Ektar100')
        orig = ORIG_DE.get(base, '?')
        delta = f'{de - orig:+.2f}' if isinstance(orig, float) else '?'
        print(f'{name:<22}{orig:<10}{de:<10}{delta}')

    json.dump([{'key': k, 'name': n, 'de': d} for k, n, d in results],
              open(os.path.join(CUBE_DIR, 'cal_fit_results.json'), 'w'),
              ensure_ascii=False, indent=2)
    print(f'\n结果已存: {CUBE_DIR}/cal_fit_results.json')

if __name__ == '__main__':
    main()
