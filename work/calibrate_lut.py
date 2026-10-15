#!/usr/bin/env python3
"""胶片 LUT 色彩特性校准器（底层改写）。

把英泽君的 cube 作为「忠实基底」，再叠加一层「特性校准」，
让每个 LUT 更贴合该胶片的**真实色彩特性**（依据国内外权威资料）：

校准器在 sRGB 域对 LUT 的 33³ 输出节点做定向偏移，三个可解释的杠杆：
  1. white_balance : (r_gain, b_gain)  —— 整体色温/品红偏移（灰轴优先）
  2. hue_tune      : {色相名: (sat_scale, hue_shift_deg)} —— 六色相定向校准
  3. shadow_lift   : (r_lift, b_lift)  —— 暗部 RGB 抬升（修 5219 暗部偏蓝）

每个胶片一套「目标特性」参数，依据注释里的权威结论，可随时手调。
"""
import os, sys
import numpy as np
import colour
from colour.models import RGB_to_HSV, HSV_to_RGB

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # gr3-film-mods
WORK = os.path.join(HERE, 'work')


def load_cube(path):
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    n = None
    domain_min = [0, 0, 0]
    domain_max = [1, 1, 1]
    header = []
    data = []
    for ln in lines:
        s = ln.rstrip('\n')
        st = s.strip()
        if not st or st.startswith('#'):
            header.append(s)
            continue
        if st.startswith('TITLE'):
            header.append(s)
            continue
        if st.startswith('LUT_3D_SIZE'):
            n = int(st.split()[-1])
            header.append(s)
            continue
        if st.startswith('LUT_1D_SIZE'):
            header.append(s)
            continue
        if st.startswith('DOMAIN_MIN'):
            domain_min = [float(x) for x in st.split()[1:4]]
            header.append(s)
            continue
        if st.startswith('DOMAIN_MAX'):
            domain_max = [float(x) for x in st.split()[1:4]]
            header.append(s)
            continue
        vals = [float(x) for x in st.split()]
        if len(vals) == 3:
            data.append(vals)
    arr = np.array(data, dtype=np.float64)
    if n is None:
        n = int(round(arr.shape[0] ** (1/3)))
    lut = arr.reshape(n, n, n, 3)
    return header, lut, n


def write_cube(path, header, lut, title=None):
    n = lut.shape[0]
    out = []
    for h in header:
        if h.strip().startswith('TITLE') and title:
            out.append(f'TITLE "{title}"')
        elif h.strip().startswith('TITLE'):
            out.append(h)
        elif h.strip().startswith('LUT_3D_SIZE'):
            out.append(f'LUT_3D_SIZE {n}')
        else:
            out.append(h)
    if not any(x.strip().startswith('TITLE') for x in out):
        out.insert(0, f'TITLE "{title or "calibrated"}"')
    flat = lut.reshape(-1, 3)
    for v in flat:
        out.append(f'{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}')
    with open(path, 'w') as f:
        f.write('\n'.join(out) + '\n')
    return path


def white_balance(lut, r_gain, b_gain):
    """整体 R/B 增益（对灰轴做色温/品红偏移）。r_gain>1 变暖，b_gain>1 变冷。"""
    out = lut.copy()
    out[..., 0] = np.clip(out[..., 0] * r_gain, 0, 1)
    out[..., 2] = np.clip(out[..., 2] * b_gain, 0, 1)
    return out


def shadow_lift(lut, r_lift, b_lift, range_lo=0.0, range_hi=0.35, falloff=0.12):
    """暗部 RGB 抬升（只动低明度区，平滑过渡到零）。修 5219 暗部偏蓝。"""
    out = lut.copy()
    v = np.max(out, axis=-1)  # 每节点明度
    # 权重：range_lo 前=1，range_hi 后=0，之间平滑
    w = np.clip((range_hi - v) / (range_hi - range_lo), 0, 1)
    w = np.clip(w / max(falloff, 1e-6), 0, 1)  # 额外软化
    out[..., 0] = np.clip(out[..., 0] + r_lift * w, 0, 1)
    out[..., 2] = np.clip(out[..., 2] + b_lift * w, 0, 1)
    return out


def hue_tune(lut, hue_map):
    """六色相定向校准。hue_map: {色相名: (sat_scale, hue_shift_deg)}。

    对每个 LUT 输出节点按它在 HSV 色相环上的位置，对目标色相附近的
    像素施加平滑的饱和度缩放 + 色相偏移（按色相距离高斯加权，避免硬切）。
    """
    n = lut.shape[0]
    flat = lut.reshape(-1, 3)
    hsv = RGB_to_HSV(flat)  # (N,3) hue in [0,1]
    hue = hsv[:, 0] * 360.0  # 度

    # 目标色相锚点（度）
    anchors = {
        'R': 0.0, 'Y': 60.0, 'G': 120.0, 'C': 180.0, 'B': 240.0, 'M': 300.0,
    }
    sat_scale_total = np.ones(len(flat))
    hue_shift_total = np.zeros(len(flat))
    for name, (sat_s, hue_s) in hue_map.items():
        a = anchors[name]
        # 色相环距离（最小角差）
        d = np.abs(hue - a)
        d = np.minimum(d, 360 - d)
        # 高斯权重，σ=30°
        w = np.exp(-(d ** 2) / (2 * 30.0 ** 2))
        sat_scale_total += (sat_s - 1.0) * w
        hue_shift_total += hue_s * w

    hsv[:, 1] = np.clip(hsv[:, 1] * sat_scale_total, 0, 1)
    hsv[:, 0] = np.clip(hsv[:, 0] + hue_shift_total / 360.0, 0, 1)
    out_flat = HSV_to_RGB(hsv)
    return np.clip(out_flat, 0, 1).reshape(n, n, n, 3)


# ---------------------------------------------------------------------------
# 每款胶片的「目标特性」参数（依据权威资料，可手调）
# ---------------------------------------------------------------------------
# 权威结论摘要：
#  Portra 400 : 暖金、肤色暖、红橙**克制不饱和**、冷色柔、pastel。
#  Ektar 100  : 高饱和、蓝绿极艳、肤色偏红/品红、高反差、偏暖。
#  5207(250D) : 日光平衡、干净自然、中性偏一点暖。
#  5219(500T) : 钨丝灯片，暖调+品红，暗部偏蓝是化学特性（但不宜过极端）。

FILM_RECIPES = {
    'Portra400': dict(
        title='Portra 400',
        white_balance=(1.015, 0.99),   # 轻微加暖（肤色暖）
        hue_tune={
            'R': (0.92, +2.0),    # 红饱和降 8%（克制红橙）
            'Y': (0.97, +1.0),    # 黄略降，保持暖但不艳
            'G': (0.99, 0.0),     # 绿基本不动（自然）
            'C': (0.97, 0.0),     # 青柔化（冷色软）
            'B': (0.98, 0.0),     # 蓝柔化（收敛幅度，别砍太狠）
            'M': (1.00, +1.0),    # 品红微提（暖金方向）
        },
        shadow_lift=(0.0, 0.0),
    ),
    'Ektar100': dict(
        title='Ektar 100',
        white_balance=(1.018, 0.985),   # 加暖+品红（肤色偏红/品红，高反差）—— 收敛
        hue_tune={
            'R': (1.04, 0.0),     # 红提饱和（肤色偏红，收敛）
            'Y': (1.01, 0.0),
            'G': (1.03, +1.0),    # 绿提饱和（风光绿，收敛）
            'C': (1.05, 0.0),     # 青提饱和（收敛）
            'B': (1.06, 0.0),     # 蓝提饱和（天空深蓝，收敛）
            'M': (1.03, +1.5),    # 品红提+偏移（收敛）
        },
        shadow_lift=(0.0, 0.0),
    ),
    '5207': dict(
        title='Kodak 5207',
        white_balance=(1.01, 0.995),   # 日光干净，极轻微暖
        hue_tune={
            'R': (0.98, 0.0),
            'Y': (0.99, 0.0),
            'G': (1.00, 0.0),
            'C': (1.00, 0.0),
            'B': (1.00, 0.0),
            'M': (1.00, 0.0),
        },
        shadow_lift=(0.0, 0.0),
    ),
    '5219': dict(
        title='Kodak 5219',
        white_balance=(1.02, 0.985),   # 暖调+品红（钨丝灯暖魂）
        hue_tune={
            'R': (0.98, 0.0),
            'Y': (1.00, 0.0),
            'G': (0.98, 0.0),
            'C': (0.98, 0.0),
            'B': (0.98, 0.0),
            'M': (1.03, +1.5),    # 品红提（5219 的品红底）
        },
        shadow_lift=(0.008, 0.022),   # 暗部抬 R 少量、B 更多 → 修暗部偏蓝（收敛减半）
    ),
}


def calibrate(lut, recipe):
    """按配方叠加三级校准，返回新 LUT。"""
    out = lut.copy()
    if recipe.get('white_balance'):
        r_g, b_g = recipe['white_balance']
        out = white_balance(out, r_g, b_g)
    if recipe.get('hue_tune'):
        out = hue_tune(out, recipe['hue_tune'])
    if recipe.get('shadow_lift'):
        r_l, b_l = recipe['shadow_lift']
        out = shadow_lift(out, r_l, b_l)
    return out


# 输入：英泽君推荐基底
SOURCE = {
    'Portra400': '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/英泽君的真彩色Portra400 Liit/原 RCP400 -S.cube',
    '5207': '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/英泽君的Kodak5207 Liit版/原 5207 - S.cube',
    '5219': '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/英泽君柯达5219 Liit版/标 5219 - S.cube',
    'Ektar100': '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/英泽君柯达Ektar100V2 Liit版/原 Ektar100 - S.cube',
}


def main():
    outdir = os.path.join(WORK, 'yingzejun_cubes', 'calibrated')
    os.makedirs(outdir, exist_ok=True)
    for film, src in SOURCE.items():
        if not os.path.exists(src):
            print(f'[跳过] {film}: 源文件不存在')
            continue
        header, lut, n = load_cube(src)
        rec = FILM_RECIPES[film]
        cal = calibrate(lut, rec)
        outpath = os.path.join(outdir, f'{film}_calibrated.cube')
        write_cube(outpath, header, cal, rec['title'])
        print(f'[OK] {film}: {n}³ -> {outpath}')
    print(f'\n校准后 cube 已写入: {outdir}')


if __name__ == '__main__':
    main()
