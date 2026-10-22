"""Duccio 专属胶片拟合 —— 基于 cube_fit.py 改造（2026-10-11）。

与作者管线的差异：
1. base_gamma：作者靠仿真 dump work/base_gamma_std.npy（未提交）。本脚本用解析重建：
   BASE[i] = 16384 * sRGB_encode(clip(i/K, 0, 1))，K = 7.8/0.18（18% 灰 -> sRGB 0.46 -> 索引 7.8，
   作者注释中的假设 + 真机验证 §「dE 3.4 残差=镜头阴影」）。已验证与作者模型语义等价
   （lin=0.18 处误差 0.0002）。重建表写回 work/base_gamma_std.npy。
   局限：线性 >= 1.0（索引 >= 43）饱和为白 —— 显示域物理上成立，高光 >= +2.5 档本就趋于白。
   待办：拍 RAW+JPG 色卡后可微调 K 与阴影段（FINDINGS §13 建议的校准）。
2. 输入编码 'srgb'：Duccio 的 cube（GR3配方/NIGHT500T、CINEMA50D）是 sRGB 显示域 LUT
   （作用于相机 JPG）。目标函数：T(L) = LUT(sRGB_encode(clip(L*2^ev, 0, 1)))。

用法：duccio_fit.py out.json srgb cube[:ev] [cube[:ev] ...] [--boost W]
"""
import sys, json, os
import numpy as np
import colour
from scipy.optimize import least_squares

HERE = os.path.dirname(os.path.abspath(__file__))
STD_LOOK = np.array([8116, 743, -667, 15, 8598, -421, -244, 542, 7894]).reshape(3, 3) / 8192
MID_INDEX = 7.8
K = MID_INDEX / 0.18
SRGB = colour.RGB_COLOURSPACES['sRGB']


def _reconstruct_base_gamma():
    """解析重建 Standard 256 点 gamma 表（等价于作者仿真 dump 的模型语义）。"""
    path = os.path.join(HERE, 'work/base_gamma_std.npy')
    i = np.arange(256)
    BASE = np.round(np.clip(16384.0 * SRGB.cctf_encoding(np.clip(i / K, 0, None)), 0, 16384))
    np.save(path, BASE)
    return BASE.astype(float)


if not os.path.exists(os.path.join(HERE, 'work/base_gamma_std.npy')):
    _reconstruct_base_gamma()
BASE = np.load(os.path.join(HERE, 'work/base_gamma_std.npy')).astype(float)


def base_gamma(lin):
    return np.interp(np.clip(K * lin, 0, 255), np.arange(256), BASE)


def apply_curve(curve, g):
    return np.interp(np.clip(g / 64.0, 0, 255), np.arange(256), curve)


def warm_samples(n=1500, seed=2):
    rng = np.random.default_rng(seed)
    h = rng.uniform(15, 90, n) / 360; s = rng.uniform(0.35, 1.0, n); v = np.ones(n)
    rgb = colour.HSV_to_RGB(np.stack([h, s, v], 1))
    lin = SRGB.cctf_decoding(rgb)
    lin = lin / lin.max(1, keepdims=True) * 0.18 * 2.0 ** rng.uniform(-2.5, 2.0, (n, 1)) * 1.5
    return lin


def near_neutral_samples(n=1500, seed=3):
    rng = np.random.default_rng(seed)
    lin = 1 + rng.uniform(-0.08, 0.08, (n, 3))
    return lin * 0.18 * 2.0 ** rng.uniform(-5, 3, (n, 1))


def samples(seed=1, boost=0.0):
    rng = np.random.default_rng(seed)
    gray = 0.18 * 2.0 ** np.linspace(-7, 4.5, 600)
    gray = np.repeat(gray[:, None], 3, 1)
    cc = colour.CCS_COLOURCHECKERS['ColorChecker24 - After November 2014']
    xyz = colour.xyY_to_XYZ(np.array(list(cc.data.values())))
    xyz = colour.chromatic_adaptation(xyz, colour.xy_to_XYZ(cc.illuminant), colour.xy_to_XYZ(SRGB.whitepoint))
    chart = np.clip(colour.XYZ_to_RGB(xyz, SRGB, apply_cctf_encoding=False), 0, None)
    charts = np.concatenate([chart * 2.0 ** ev for ev in (-2, -1, 0, 1, 2)])
    cw = np.tile(np.where(np.arange(24) < 2, 60.0, 20.0), 5)
    rnd = rng.random((6000, 3)) ** 2.2 * 2.0 ** rng.uniform(-4, 2, (6000, 1)) * 0.6
    L = np.concatenate([gray, charts, rnd])
    w = np.concatenate([np.full(len(gray), 150.0), cw, np.ones(len(rnd))])
    if boost:
        warm, neu = warm_samples(), near_neutral_samples()
        L = np.concatenate([L, warm, neu])
        w = np.concatenate([w, np.full(len(warm), boost * cw.sum() / len(warm)),
                            np.full(len(neu), NEUTRAL * boost * cw.sum() / len(neu))])
    return L, w, chart


def load_target(path, in_cs, ev):
    lut = colour.read_LUT(path)
    if in_cs == 'vlog':
        vg = colour.RGB_COLOURSPACES['V-Gamut']

        def T(L):
            x = colour.RGB_to_RGB(L * 2.0 ** ev, SRGB, vg)
            x = colour.models.log_encoding_VLog(np.clip(x, 0, None))
            return np.clip(lut.apply(x, interpolator=colour.algebra.table_interpolation_tetrahedral), 0, 1)
        return T
    elif in_cs == 'srgb':
        # Duccio 显示域 cube：作用于 sRGB 编码后的 JPG 值
        def T(L):
            x = SRGB.cctf_encoding(np.clip(L * 2.0 ** ev, 0, None))
            return np.clip(lut.apply(np.clip(x, 0, 1), interpolator=colour.algebra.table_interpolation_tetrahedral), 0, 1)
        return T
    raise SystemExit(f'unsupported input encoding: {in_cs}')


def fit_curve(g, t, w, lam=3000.0):
    x = np.clip(g / 64.0, 0, 255)
    i0 = np.minimum(x.astype(int), 254); f = x - i0
    A = np.zeros((256, 256)); b = np.zeros(256)
    for a_i, a_w in ((i0, 1 - f), (i0 + 1, f)):
        for b_i, b_w in ((i0, 1 - f), (i0 + 1, f)):
            np.add.at(A, (a_i, b_i), w * a_w * b_w)
        np.add.at(b, a_i, w * a_w * t * 16384)
    D = np.diff(np.eye(256), 2, axis=0)
    c = np.linalg.solve(A + lam * D.T @ D + 1e-6 * np.eye(256), b)
    c = np.maximum.accumulate(np.clip(c, 0, 16383))
    return np.round(c).astype(int)


def model(M, curves, L):
    lin = L @ M.T
    return np.stack([apply_curve(curves[c], base_gamma(lin[:, c])) for c in range(3)], 1) / 16384


def M_from(p):
    off = p.reshape(3, 2)
    M = np.zeros((3, 3))
    for r in range(3):
        o = [j for j in range(3) if j != r]
        M[r, o] = off[r]; M[r, r] = 1 - off[r].sum()
    return M


BOOST = 0.0
NEUTRAL = 1.0


def fit(targets, iters=8):
    L, w, chart = samples(boost=BOOST)
    Ts = [T(L) for T in targets]
    p = np.zeros(6)
    for it in range(iters):
        M = M_from(p)
        lin = L @ M.T
        curves = [[fit_curve(base_gamma(lin[:, c]), Tt[:, c], w) for c in range(3)] for Tt in Ts]

        def res(p):
            Mp = M_from(p)
            return np.concatenate([(np.sqrt(w)[:, None] * (model(Mp, cv, L) - Tt)).ravel() for cv, Tt in zip(curves, Ts)])
        p = least_squares(res, p, x_scale=0.1).x
        rms = np.sqrt(np.mean(res(p) ** 2))
        print(f'iter {it}: weighted rms {rms*255:.2f} /255  M diag {np.round(np.diag(M_from(p)),3)}')
    M = M_from(p)
    lin = L @ M.T
    curves = [[fit_curve(base_gamma(lin[:, c]), Tt[:, c], w) for c in range(3)] for Tt in Ts]
    return M, curves, chart


def de2000(a, b):
    lab = lambda x: colour.XYZ_to_Lab(colour.sRGB_to_XYZ(np.clip(x, 0, 1)))
    return colour.delta_E(lab(a), lab(b), method='CIE 2000')


def split_spec(s):
    """把 'path[:ev]' 拆成 (path, ev:float)。兼容 Windows 盘符冒号（C:\\...）。"""
    path, _, ev = s.rpartition(':')
    if path and ev:
        try:
            return path, float(ev)
        except ValueError:
            pass
    return s, 0.0


if __name__ == '__main__':
    args = sys.argv[1:]
    if args[0] == '--boost':
        BOOST = float(args[1])
        args = args[2:]
    out, in_cs, specs = args[0], args[1], args[2:]
    targets = []
    for s in specs:
        path, ev = split_spec(s)
        targets.append(load_target(path, in_cs, ev))
    M, curves, chart = fit(targets)
    std = np.stack([base_gamma((chart @ STD_LOOK.T)[:, c]) for c in range(3)], 1) / 16384
    report = []
    for spec, T, cv in zip(specs, targets, curves):
        tgt = T(chart)
        d_fit, d_std = de2000(model(M, cv, chart), tgt), de2000(std, tgt)
        print(f'{os.path.basename(spec)}: chart dE2000 fit mean {d_fit.mean():.2f} max {d_fit.max():.2f} | '
              f'Standard-vs-target mean {d_std.mean():.2f}')
        gray = tgt[[18, 19, 20, 21, 22, 23]]
        report.append(dict(spec=spec, curves=[list(map(int, c)) for c in cv],
                           chart_de_mean=float(d_fit.mean()), chart_de_max=float(d_fit.max()),
                           std_de_mean=float(d_std.mean()), target_gray_row=np.round(gray * 255).tolist(),
                           fit_chart=np.round(model(M, cv, chart) * 255).tolist(), target_chart=np.round(tgt * 255).tolist(),
                           std_chart=np.round(std * 255).tolist()))
    print('M =', np.round(M, 4).tolist())
    json.dump(dict(matrix=M.tolist(), mid_index=MID_INDEX, base_gamma='analytic-reconstruction',
                   presets=report), open(out, 'w'))
    print('已写出', out)
