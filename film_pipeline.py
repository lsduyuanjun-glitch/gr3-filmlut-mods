#!/usr/bin/env python3
"""胶片自动管线：HALD 图 -> cube -> 三阶段 v12 拟合 -> 返回 ΔE。

这是网页端「新建胶片」的后端核心，把之前手工跑的三步串成一条：
  1. HALD 512×512 图 -> .cube（xmp2cube.hald512_to_lut）
  2. cube_fit.py  --boost 4 --neutral 3 -> 第一层（matrix + curves）
  3. joint_fit.py -> 第二层（cca1_q512）
  4. lab_fit.py   -> 第三层（post_q512 + lab_fit.after.colorchecker）

用法（供 server.py 调用）：
  from film_pipeline import run_film
  result = run_film(hald_path, film_key, display_name, box_spec)
"""
import sys, os, json, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FITS_DIR = os.path.join(HERE, 'work', 'films_v11', 'fits')


def hald512_to_cube(hald_path, cube_path, title='Film LUT'):
    """把 512×512（64³）HALD 图转成 .cube。"""
    sys.path.insert(0, HERE)
    import xmp2cube
    import tifffile
    arr = tifffile.imread(hald_path)
    lut = xmp2cube.hald512_to_lut(arr)
    xmp2cube.write_cube(lut, cube_path, title)
    return cube_path


def gray_axis_check(cube_path):
    """灰轴健康检查：返回若干档输入中性灰对应的输出 R/B 比例。"""
    sys.path.insert(0, HERE)
    import colour
    lut = colour.read_LUT(cube_path)
    rows = []
    for v in [0.05, 0.1, 0.18, 0.25, 0.5, 0.75, 0.9, 1.0]:
        out = lut.apply(np.array([[v, v, v]]),
                        interpolator=colour.algebra.table_interpolation_tetrahedral)[0]
        rb = out[0] / max(out[2], 1e-6)
        rows.append({'in': round(v, 2), 'r': round(float(out[0]), 3),
                     'g': round(float(out[1]), 3), 'b': round(float(out[2]), 3),
                     'rb': round(float(rb), 3)})
    return rows


def run_fit(cube_path, film_key, boost=4, neutral=3):
    """三阶段拟合，返回 (fit_path, de_final)。"""
    base = os.path.join(FITS_DIR, f'{film_key}_b{boost}n{neutral}')
    b4n3 = f'{base}.json'
    joint = f'{base}_joint.json'
    lab = f'{base}_lab.json'

    # 1) cube_fit
    r = subprocess.run([sys.executable, os.path.join(HERE, 'cube_fit.py'),
                        '--boost', str(boost), '--neutral', str(neutral),
                        b4n3, 'srgb', cube_path],
                       capture_output=True, text=True, cwd=HERE, timeout=180)
    if r.returncode != 0:
        raise RuntimeError('cube_fit 失败: ' + r.stderr[-1500:])

    # 2) joint_fit
    r = subprocess.run([sys.executable, os.path.join(HERE, 'joint_fit.py'), b4n3, joint],
                       capture_output=True, text=True, cwd=HERE, timeout=180)
    if r.returncode != 0:
        raise RuntimeError('joint_fit 失败: ' + r.stderr[-1500:])

    # 3) lab_fit
    r = subprocess.run([sys.executable, os.path.join(HERE, 'lab_fit.py'), joint, lab],
                       capture_output=True, text=True, cwd=HERE, timeout=180)
    if r.returncode != 0:
        raise RuntimeError('lab_fit 失败: ' + r.stderr[-1500:])

    d = json.load(open(lab))
    after = d.get('lab_fit', {}).get('after', {})
    de = after.get('colorchecker', after.get('chart', 0))
    return lab, round(float(de), 2)


def run_film(hald_path, film_key, display_name, box_spec, cube_dir, boost=4, neutral=3):
    """完整跑一个胶片（HALD 图入口），返回结构化结果（供 server 写入胶片库）。

    box_spec: (body_rgb, strip_rgb, brand_col, name, name_col, speed, speed_col)
    """
    os.makedirs(cube_dir, exist_ok=True)
    cube_path = os.path.join(cube_dir, f'{film_key}.cube')
    hald512_to_cube(hald_path, cube_path, display_name)
    return _finish_film(cube_path, film_key, display_name, box_spec, boost, neutral)


def run_film_from_cube(cube_path_src, film_key, display_name, box_spec, cube_dir, boost=4, neutral=3):
    """完整跑一个胶片（.cube 直读入口）：直接用现成 cube 拟合，跳过 HALD 转 cube。"""
    os.makedirs(cube_dir, exist_ok=True)
    cube_path = os.path.join(cube_dir, f'{film_key}.cube')
    import shutil
    shutil.copy(cube_path_src, cube_path)
    return _finish_film(cube_path, film_key, display_name, box_spec, boost, neutral)


def run_film_from_xmp(xmp_path, film_key, display_name, box_spec, cube_dir, size=64, boost=4, neutral=3):
    """完整跑一个胶片（XMP 直读入口）：解析 .xmp Look 预设 -> 3D LUT -> cube -> 拟合。

    这是「全自动」路径：不需要 Lightroom 套预设导 HALD 图，直接读 XMP 的 crs:Look 表。
    """
    os.makedirs(cube_dir, exist_ok=True)
    sys.path.insert(0, HERE)
    import xmp_reader
    res = xmp_reader.xmp_to_lut(xmp_path, size=size)
    lut = res['lut']
    cube_path = os.path.join(cube_dir, f'{film_key}.cube')
    # 写 cube（R 通道变化最快，与 xmp2cube.write_cube 的遍历顺序一致）
    n = lut.shape[0]
    lines = [f'TITLE "{display_name}"', f'LUT_3D_SIZE {n}',
             'DOMAIN_MIN 0.0 0.0 0.0', 'DOMAIN_MAX 1.0 1.0 1.0']
    for b in range(n):
        for g in range(n):
            for r in range(n):
                v = lut[r, g, b]
                lines.append(f'{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}')
    open(cube_path, 'w').write('\n'.join(lines) + '\n')
    result = _finish_film(cube_path, film_key, display_name, box_spec, boost, neutral)
    result['xmp'] = {'title': res['title'], 'rgb_div': res['rgb_div'],
                     'look_dims': res['look_dims'], 'size': n}
    return result


def _finish_film(cube_path, film_key, display_name, box_spec, boost, neutral):
    """共用收尾：灰轴检查 + 三阶段拟合 + 返回结果。"""
    gray = gray_axis_check(cube_path)
    fit_path, de = run_fit(cube_path, film_key, boost, neutral)
    rel_fit = os.path.relpath(fit_path, HERE)
    return {
        'key': film_key,
        'name': display_name,
        'de': de,
        'cube': os.path.basename(cube_path),
        'fit': rel_fit,
        'gray': gray,
        'box': box_spec,
        # 12 分区色相（MultiAxial hue sectors）：中性恒等矩阵（12×3×3，每行和 1024）。
        # 让新建胶片能被 v16 构建管线（make_slots16.patch_ma）识别并启用 12 分区色相能力，
        # 默认不做色相偏移；后续如需按胶片特性偏移，可在这里替换为实际 12 分区矩阵。
        'hue_q10': [[[1024, 0, 0], [0, 1024, 0], [0, 0, 1024]] for _ in range(12)],
    }
