#!/usr/bin/env python3
"""HALD 身份图 <-> .cube LUT 转换工具（消除断层的高精度实现）。

把 Lightroom/PS 的 XMP 预设转成通用 .cube LUT，业界标准做法是「HALD 身份图法」：
  1. 生成一张「HALD 身份图」——把 3D LUT 每个采样点平铺成 2D 图像，每个像素
     恰等于一个输入 RGB 值（恒等映射）。
  2. 在 Lightroom 里套预设，无损导出。
  3. 解析回 3D LUT，写 .cube。

断层根因：用 JPG 导出（有损）+ 采样密度低。本工具用 16-bit TIFF + 64³ 采样。

用法：
  python xmp2cube.py gen 16            # 生成 16-bit 身份图
  python xmp2cube.py convert <edited.tif> <out.cube>
  python xmp2cube.py selftest 16       # 无损往返验证
"""
import sys, os
import numpy as np
from PIL import Image


def lut_size_from_hald(w, h):
    n = int(round(w ** 0.5))
    if n * n != w or h != n:
        raise ValueError(f'HALD 尺寸异常：{w}x{h}，期望 N*N x N')
    return n


def make_identity_hald(n, bit_depth=16):
    total = n ** 3
    if bit_depth == 16:
        maxv, dtype = 65535, np.uint16
    else:
        maxv, dtype = 255, np.uint8
    vals = np.round(np.arange(n, dtype=np.float64) * (maxv / (n - 1))).astype(dtype)
    idx = np.arange(total)
    r = idx % n
    g = (idx // n) % n
    b = idx // (n * n)
    flat = np.zeros((total, 3), dtype=dtype)
    flat[:, 0] = vals[r]
    flat[:, 1] = vals[g]
    flat[:, 2] = vals[b]
    img = flat.reshape(n, n * n, 3)
    if bit_depth == 16:
        return img.astype(np.uint16)
    return Image.fromarray(img, 'RGB')


def hald_to_lut(img, n):
    arr = np.asarray(img)
    if arr.dtype == np.uint16 or arr.max() > 255:
        arr = arr.astype(np.float64) / 65535.0
    else:
        arr = arr.astype(np.float64) / 255.0
    lut = arr.reshape(n, n, n, 3)
    lut = lut.transpose(2, 1, 0, 3)
    return lut


def hald512_to_lut(img):
    """把 512×512（64³）HALD 图转成 64³ LUT。

    512×512 排布（实测恒等往返 err=0.0000）：
      r = col % 64
      g = col // 64 + (row % 8) * 8
      b = row // 8
    """
    n = 64
    arr = np.asarray(img)
    if arr.dtype == np.uint16 or arr.max() > 255:
        arr = arr.astype(np.float64) / 65535.0
    else:
        arr = arr.astype(np.float64) / 255.0
    rows, cols = np.mgrid[0:512, 0:512]
    r = cols % n
    g = cols // n + (rows % 8) * 8
    b = rows // 8
    lut = np.zeros((n, n, n, 3))
    lut[r, g, b] = arr
    return lut


def make_identity_hald512():
    """生成 512×512 16-bit 线性 sRGB 身份图（对应 hald512_to_lut 的排布）。"""
    n = 64
    rows, cols = np.mgrid[0:512, 0:512]
    r = cols % n
    g = cols // n + (rows % 8) * 8
    b = rows // 8
    vals = np.round(np.arange(n, dtype=np.float64) * (65535.0 / (n - 1))).astype(np.uint16)
    img = np.stack([vals[r], vals[g], vals[b]], axis=-1).astype(np.uint16)
    return img


def write_cube(lut, path, title='HALD LUT'):
    n = lut.shape[0]
    lines = [f'TITLE "{title}"', f'LUT_3D_SIZE {n}', 'DOMAIN_MIN 0.0 0.0 0.0', 'DOMAIN_MAX 1.0 1.0 1.0']
    for b in range(n):
        for g in range(n):
            for r in range(n):
                v = lut[r, g, b]
                lines.append(f'{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}')
    open(path, 'w').write('\n'.join(lines) + '\n')
    return path


def read_hald_image(path):
    import tifffile
    if path.lower().endswith(('.tif', '.tiff')):
        arr = tifffile.imread(path)
        h, w = arr.shape[0], arr.shape[1]
        n = lut_size_from_hald(w, h)
        return arr, n
    img = Image.open(path).convert('RGB')
    w, h = img.size
    n = lut_size_from_hald(w, h)
    return np.asarray(img), n


def gen(n=64, bits=16, out=None):
    out = out or f'hald_{n}_{bits}bit.tif'
    img = make_identity_hald(n, bits)
    if bits == 16:
        import tifffile
        tifffile.imwrite(out, img, photometric='rgb')
        print(f'已生成 HALD 身份图 {out}（{n*n}x{n}，16-bit TIFF，{n**3} 采样点）')
    else:
        img.save(out)
        print(f'已生成 HALD 身份图 {out}（{n*n}x{n}，8-bit PNG，{n**3} 采样点）')
    print('下一步：Lightroom 套预设后以 TIFF/PNG 无损导出（勿用 JPG），再 convert 转 cube')


def convert(inp, out):
    img, n = read_hald_image(inp)
    lut = hald_to_lut(img, n)
    write_cube(lut, out)
    print(f'已生成 {out}（LUT_3D_SIZE {n}）')


def selftest(bits=16):
    n = 16
    img = make_identity_hald(n, bits)
    lut = hald_to_lut(img, n)
    max_err = 0.0
    for r in [0, n // 2, n - 1]:
        for g in [0, n // 2, n - 1]:
            for b in [0, n // 2, n - 1]:
                expect = np.array([r, g, b]) / (n - 1)
                got = lut[r, g, b]
                max_err = max(max_err, np.abs(got - expect).max())
    print(f'{bits}-bit 无损往返最大误差: {max_err:.6f}')
    print('恒等验证:', 'PASS' if max_err < 0.002 else 'FAIL')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == 'gen':
        gen(64, int(sys.argv[2]) if len(sys.argv) > 2 else 16, sys.argv[3] if len(sys.argv) > 3 else None)
    elif cmd == 'convert':
        convert(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'output.cube')
    elif cmd == 'selftest':
        selftest(int(sys.argv[2]) if len(sys.argv) > 2 else 16)
    else:
        print(__doc__)
