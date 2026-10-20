#!/usr/bin/env python3
"""胶片自动管线：HALD 图 -> cube -> 三阶段 v12 拟合 -> 返回 ΔE。

这是网页端「新建胶片」的后端核心，把之前手工跑的三步串成一条：
  1. HALD 512×512 图 -> .cube（xmp2cube.hald512_to_lut）
  2. cube_fit.py  --boost 4 --neutral 3 -> 第一层（matrix + curves）
  3. joint_fit.py -> 第二层（cca1_q512）
  4. lab_fit.py   -> 第三层（post_q512 + lab_fit.after.colorchecker）

★ 打包版关键差异：三个拟合脚本原本用 subprocess 调用，但 PyInstaller 打包后
  sys.executable 是 app 本体，再 subprocess 会「又启动一个 app 实例」。
  改为进程内执行（runpy + 临时替换 sys.argv / cwd），行为与命令行完全一致。

用法（供 server.py 调用）：
  from film_pipeline import run_film
  result = run_film(hald_path, film_key, display_name, box_spec, cube_dir)
"""
import io
import os
import contextlib
import runpy
import sys
import json

import numpy as np

# paths.py 放在 webtool/（网页端共用）；开发环境下本文件在仓库根，需要把它加进搜索路径。
# 打包环境下所有 .py 平铺在同一目录，这步是无害的空操作。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'webtool'))
import paths  # noqa: E402

RESOURCE = paths.RESOURCE_DIR
# 拟合产物写入「用户可写目录」，不写进只读的 app 包内部
FITS_DIR = paths.FITS_DIR


def _run_script(script_name, argv, cwd):
    """在进程内执行引擎脚本，行为等价于 `python script.py <argv>`。

    为什么不用 subprocess：PyInstaller 打包后没有可独立调用的 Python 解释器，
    sys.executable 指向 app 本体，再起子进程等于重复启动整个 app。
    这里用 runpy 在当前进程里跑，并临时接管 sys.argv / cwd / stdout。
    返回 (returncode, output)；脚本抛异常时 returncode=1 且 output 含 traceback。
    """
    script_path = os.path.join(RESOURCE, script_name)
    old_argv, old_cwd = sys.argv, os.getcwd()
    buf = io.StringIO()
    try:
        sys.argv = [script_path] + list(argv)
        os.chdir(cwd)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            runpy.run_path(script_path, run_name='__main__')
        return 0, buf.getvalue()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        return code, buf.getvalue()
    except Exception:
        import traceback
        return 1, buf.getvalue() + '\n' + traceback.format_exc()
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)


def hald512_to_cube(hald_path, cube_path, title='Film LUT'):
    """把 512×512（64³）HALD 图转成 .cube。"""
    sys.path.insert(0, RESOURCE)
    import xmp2cube
    import tifffile
    arr = tifffile.imread(hald_path)
    lut = xmp2cube.hald512_to_lut(arr)
    xmp2cube.write_cube(lut, cube_path, title)
    return cube_path


def gray_axis_check(cube_path):
    """灰轴健康检查：返回若干档输入中性灰对应的输出 R/B 比例。"""
    sys.path.insert(0, RESOURCE)
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
    """三阶段拟合，返回 (fit_path, de_final)。进程内依次执行三个拟合脚本。"""
    os.makedirs(FITS_DIR, exist_ok=True)
    base = os.path.join(FITS_DIR, f'{film_key}_b{boost}n{neutral}')
    b4n3 = f'{base}.json'
    joint = f'{base}_joint.json'
    lab = f'{base}_lab.json'

    # 1) cube_fit（cwd=RESOURCE，脚本内按相对路径读 work/base_gamma_std.npy）
    code, out = _run_script('cube_fit.py',
                            ['--boost', str(boost), '--neutral', str(neutral),
                             b4n3, 'srgb', cube_path], RESOURCE)
    if code != 0:
        raise RuntimeError('cube_fit 失败: ' + out[-1500:])

    # 2) joint_fit
    code, out = _run_script('joint_fit.py', [b4n3, joint], RESOURCE)
    if code != 0:
        raise RuntimeError('joint_fit 失败: ' + out[-1500:])

    # 3) lab_fit
    code, out = _run_script('lab_fit.py', [joint, lab], RESOURCE)
    if code != 0:
        raise RuntimeError('lab_fit 失败: ' + out[-1500:])

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
    sys.path.insert(0, RESOURCE)
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
    # 存绝对路径：打包后资源目录与用户目录分离，相对路径会指错地方
    return {
        'key': film_key,
        'name': display_name,
        'de': de,
        'cube': os.path.basename(cube_path),
        'fit': fit_path,
        'gray': gray,
        'box': box_spec,
        # 12 分区色相（MultiAxial hue sectors）：中性恒等矩阵（12×3×3，每行和 1024）。
        # 让新建胶片能被 v16 构建管线（make_slots16.patch_ma）识别并启用 12 分区色相能力，
        # 默认不做色相偏移；后续如需按胶片特性偏移，可在这里替换为实际 12 分区矩阵。
        'hue_q10': [[[1024, 0, 0], [0, 1024, 0], [0, 0, 1024]] for _ in range(12)],
    }
