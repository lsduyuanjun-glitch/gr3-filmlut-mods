#!/usr/bin/env python3
"""分析英泽君 4 款胶片（Portra400/5207/5219/Ektar100）的 cube，量化色彩特性。

输出：
1. 每个 cube 的灰轴中性度（R/B 比值）
2. 三原色/三补色在 HSV 空间的饱和度、色相偏移
3. 同款胶片内部多个版本的差异（ΔE2000）
4. 与「理想胶片特性」的对照（见结论）
"""
import os, sys, glob
import numpy as np

try:
    import colour
    from colour import read_LUT
except Exception:
    read_LUT = None

# 文件清单：分组
GROUPS = {
    'Portra400': [
        '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/英泽君的真彩色Portra400 Liit/标 RCP400 -S.cube',
        '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/英泽君的真彩色Portra400 Liit/原 RCP400 -S.cube',
    ],
    '5207': [
        '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/英泽君的Kodak5207 Liit版/标1 5207 - S.cube',
        '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/英泽君的Kodak5207 Liit版/标2 5207 - S.cube',
        '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/英泽君的Kodak5207 Liit版/原 5207 - S.cube',
    ],
    '5219': [
        '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/英泽君柯达5219 Liit版/标 5219 - S.cube',
        '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/英泽君柯达5219 Liit版/标2 5219 - S.cube',
        '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/英泽君柯达5219 Liit版/原 5219 - S.cube',
    ],
    'Ektar100': [
        '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/英泽君柯达Ektar100V2 Liit版/标 Ektar100 - S.cube',
        '/Volumes/Duccio-2T/英泽君预设全套合集（Liit版）/英泽君柯达Ektar100V2 Liit版/原 Ektar100 - S.cube',
    ],
}


def load_cube(path):
    """返回 (name, lut ndarray shape (n,n,n,3), n)"""
    name = os.path.basename(path)
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    n = None
    domain_min = [0, 0, 0]
    domain_max = [1, 1, 1]
    data = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith('#'):
            continue
        if s.startswith('TITLE'):
            continue
        if s.startswith('LUT_3D_SIZE'):
            n = int(s.split()[-1])
            continue
        if s.startswith('LUT_1D_SIZE'):
            continue
        if s.startswith('DOMAIN_MIN'):
            domain_min = [float(x) for x in s.split()[1:4]]
            continue
        if s.startswith('DOMAIN_MAX'):
            domain_max = [float(x) for x in s.split()[1:4]]
            continue
        try:
            vals = [float(x) for x in s.split()]
            if len(vals) == 3:
                data.append(vals)
        except Exception:
            continue
    arr = np.array(data, dtype=np.float64)
    n = n or int(round(arr.shape[0] ** (1/3)))
    lut = arr.reshape(n, n, n, 3)
    return name, lut, n, domain_min, domain_max


def apply_lut_trilinear(lut, rgb):
    """三线性插值采样 LUT。rgb: (N,3) in [0,1]。"""
    n = lut.shape[0]
    rgb = np.clip(rgb, 0.0, 1.0)
    x = rgb * (n - 1)
    x0 = np.floor(x).astype(int)
    x1 = np.minimum(x0 + 1, n - 1)
    d = x - x0
    # 8 个角
    def idx(r, g, b):
        return lut[r, g, b]
    c000 = idx(x0[:, 0], x0[:, 1], x0[:, 2])
    c100 = idx(x1[:, 0], x0[:, 1], x0[:, 2])
    c010 = idx(x0[:, 0], x1[:, 1], x0[:, 2])
    c110 = idx(x1[:, 0], x1[:, 1], x0[:, 2])
    c001 = idx(x0[:, 0], x0[:, 1], x1[:, 2])
    c101 = idx(x1[:, 0], x0[:, 1], x1[:, 2])
    c011 = idx(x0[:, 0], x1[:, 1], x1[:, 2])
    c111 = idx(x1[:, 0], x1[:, 1], x1[:, 2])
    dx, dy, dz = d[:, 0:1], d[:, 1:2], d[:, 2:3]
    c00 = c000 * (1 - dx) + c100 * dx
    c01 = c001 * (1 - dx) + c101 * dx
    c10 = c010 * (1 - dx) + c110 * dx
    c11 = c011 * (1 - dx) + c111 * dx
    c0 = c00 * (1 - dy) + c10 * dy
    c1 = c01 * (1 - dy) + c11 * dy
    c = c0 * (1 - dz) + c1 * dz
    return c


def rgb_to_hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.max(rgb, axis=-1)
    mn = np.min(rgb, axis=-1)
    d = mx - mn
    h = np.zeros_like(mx)
    # r=max
    mask = (mx == r) & (d > 0)
    h[mask] = ((g[mask] - b[mask]) / d[mask]) % 6
    mask = (mx == g) & (d > 0)
    h[mask] = (b[mask] - r[mask]) / d[mask] + 2
    mask = (mx == b) & (d > 0)
    h[mask] = (r[mask] - g[mask]) / d[mask] + 4
    h = h / 6.0
    s = np.where(mx > 0, d / mx, 0.0)
    v = mx
    return np.stack([h, s, v], axis=-1)


def gray_axis_analysis(name, lut):
    """灰轴 R/B 比值 + 灰点亮度曲线。"""
    n = lut.shape[0]
    steps = np.linspace(0, 1, 17)
    g = np.array([[v, v, v] for v in steps])
    out = apply_lut_trilinear(lut, g)
    rb = out[:, 0] / np.maximum(out[:, 2], 1e-6)
    rg = out[:, 0] / np.maximum(out[:, 1], 1e-6)
    bg = out[:, 2] / np.maximum(out[:, 1], 1e-6)
    return {
        'name': name,
        'rb_mean': float(np.mean(rb)),
        'rb_std': float(np.std(rb)),
        'rg_mean': float(np.mean(rg)),
        'bg_mean': float(np.mean(bg)),
        'mid_luma': float(out[8, 1]),  # 中灰亮度
    }


def hue_analysis(name, lut):
    """三原色(0/120/240°)与三补色(60/180/300°)的色相/饱和度变化（用 Lab 色相角，避免 HSV 边界问题）。"""
    try:
        import colour
        from colour.models import sRGB_to_XYZ, XYZ_to_Lab
    except Exception:
        return {}
    prim = {
        'R(红)': [1, 0, 0],
        'G(绿)': [0, 1, 0],
        'B(蓝)': [0, 0, 1],
        'C(青)': [0, 1, 1],
        'M(品红)': [1, 0, 1],
        'Y(黄)': [1, 1, 0],
    }
    out = {}
    for k, c in prim.items():
        p = np.array([float(x) for x in c]).reshape(1, 3)
        o = apply_lut_trilinear(lut, p)[0]
        # sRGB -> Lab
        lab_in = XYZ_to_Lab(sRGB_to_XYZ(np.clip(np.array([c], dtype=float), 0, 1)))[0]
        lab_out = XYZ_to_Lab(sRGB_to_XYZ(np.clip(o.reshape(1, 3), 0, 1)))[0]
        # Lab 色相角
        def hue_angle(lab):
            return float(np.degrees(np.arctan2(lab[2], lab[1]))) % 360
        def chroma(lab):
            return float(np.hypot(lab[1], lab[2]))
        hi = hue_angle(lab_in)
        ho = hue_angle(lab_out)
        shift = (ho - hi + 180) % 360 - 180  # 归一到 [-180, 180]
        out[k] = {
            'rgb_in': [round(float(x), 2) for x in c],
            'rgb_out': [round(float(x), 3) for x in o],
            'chroma_in': round(chroma(lab_in), 1),
            'chroma_out': round(chroma(lab_out), 1),
            'hue_shift': round(float(shift), 1),
        }
    return out


def deltaE_between(lutA, lutB, samples=4096):
    """两 LUT 在 sRGB 采样网格上的平均 ΔE2000（先转 Lab）。"""
    try:
        import colour
        from colour.models import sRGB_to_XYZ, XYZ_to_Lab
    except Exception:
        return None
    n = int(round(samples ** (1/3)))
    grid = np.linspace(0, 1, n)
    r, g, b = np.meshgrid(grid, grid, grid, indexing='ij')
    rgb = np.stack([r.ravel(), g.ravel(), b.ravel()], axis=-1)
    oA = apply_lut_trilinear(lutA, rgb)
    oB = apply_lut_trilinear(lutB, rgb)
    # sRGB -> XYZ -> Lab
    def to_lab(x):
        xyz = sRGB_to_XYZ(np.clip(x, 0, 1))
        return XYZ_to_Lab(xyz)
    labA = to_lab(oA)
    labB = to_lab(oB)
    de = colour.delta_E(labA, labB, method='CIE 2000')
    return float(np.mean(de))


def main():
    print('=' * 78)
    print('英泽君 4 款胶片 cube 色彩特性分析')
    print('=' * 78)

    all_luts = {}
    for group, paths in GROUPS.items():
        print(f'\n### {group} ###')
        luts = []
        for p in paths:
            name, lut, n, dmin, dmax = load_cube(p)
            all_luts[f'{group}/{name}'] = lut
            luts.append((name, lut, n))
            g = gray_axis_analysis(name, lut)
            print(f'\n  [{name}]  size={n}  domain_min={dmin} domain_max={dmax}')
            print(f'    灰轴 R/B={g["rb_mean"]:.3f} (1.0=完全中性)  R/G={g["rg_mean"]:.3f}  B/G={g["bg_mean"]:.3f}  中灰亮度={g["mid_luma"]:.3f}')
        # 组内 hue 分析（取第一个做代表，多版本分别看色相）
        print(f'\n  --- 色相/饱和度（每版本）---')
        for name, lut, n in luts:
            h = hue_analysis(name, lut)
            line = []
            for k in ['R(红)', 'G(绿)', 'B(蓝)', 'C(青)', 'M(品红)', 'Y(黄)']:
                v = h[k]
                line.append(f'{k}:C{v["chroma_out"]}/hue{v["hue_shift"]:+}')
            print(f'    {name}')
            print(f'      ' + '  '.join(line))

        # 组内两两 ΔE
        if len(luts) >= 2:
            print(f'\n  --- 组内版本两两差异 (ΔE2000, 平均) ---')
            for i in range(len(luts)):
                for j in range(i + 1, len(luts)):
                    de = deltaE_between(luts[i][1], luts[j][1])
                    print(f'    {luts[i][0]}  vs  {luts[j][0]}:  ΔE = {de:.2f}' if de else '    (ΔE 计算失败)')

    print('\n' + '=' * 78)
    print('跨胶片组对照（各取第一版代表）')
    print('=' * 78)
    reps = {}
    for group, paths in GROUPS.items():
        name, lut, n, _, _ = load_cube(paths[0])
        reps[group] = lut
    keys = list(reps.keys())
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            de = deltaE_between(reps[keys[i]], reps[keys[j]])
            print(f'  {keys[i]} vs {keys[j]}: ΔE = {de:.2f}')


if __name__ == '__main__':
    main()
