#!/usr/bin/env python3
"""XMP Look 预设直读：把 Adobe Lightroom/Camera Raw 的 .xmp（PresetType="Look"）直接转成 3D LUT。

思路来源：GRMod（Maxwooow/Ricoh-GRMod，GPL-2.0）公开的 ACR Look 渲染模型，这里用 numpy/scipy
独立重写，去掉 DOM/TS 依赖，供本项目的胶片管线直接调用。

解决了之前「crs:Look 是 Adobe 私有格式、纯代码解析不可行」的痛点：
  - crs:Table_<UUID> 是 85 字符自定义 base85（每 5 字符 -> 4 字节小端），前 4 字节是
    zlib 解压后的期望长度，其余用 zlib 解压得到二进制表。
  - RGBTable（type=1, dims=3, div）: div^3 x 3 个 uint16（加 ident 后 /65535），sRGB/sRGB。
  - LookTable（type=0, hd/sd/vd）: hd*sd*vd x 3 个 float32（色相偏移度 / 饱和度缩放 / 明度缩放）。
  - ToneCurvePV2012(+Red/Green/Blue): 0..255 的曲线点。

渲染管线（Adobe Standard 基准，sRGB 显示值输入）：
  display(sRGB) -> 逆 base tone 曲线 -> 线性 ProPhoto -> LookTable(HSV) -> base tone 曲线
                -> point curve(保色相) -> RGBTable(三线性) -> 输出 sRGB

用法：
  from xmp_reader import xmp_to_lut
  lut = xmp_to_lut('xxx.xmp', size=64)   # -> numpy (size,size,size,3) float 0..1
"""
import re
import zlib
import numpy as np

# ---------------------------------------------------------------- base85 解码

# 85 字符自定义 base85 字母表（顺序即索引值），每 5 字符 -> 4 字节（小端）
ALPHA = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?`\'|()[]{}@%$#'
_IDX = {c: i for i, c in enumerate(ALPHA)}
_POW85 = [1, 85, 85 * 85, 85 * 85 * 85, 85 * 85 * 85 * 85]


def _decode_table_text(t):
    """把 crs:Table_<id> 的属性文本解码为原始字节（base85 -> zlib）。"""
    out = bytearray()
    x = 0
    k = 0
    for ch in t:
        if ch in ' \t\n\r':
            continue
        v = _IDX.get(ch)
        if v is None:
            raise ValueError('table text contains an invalid character: %r' % ch)
        x += v * _POW85[k]
        k += 1
        if k == 5:
            u = x & 0xFFFFFFFF
            out += bytes([u & 255, (u >> 8) & 255, (u >> 16) & 255, (u >> 24) & 255])
            x = 0
            k = 0
    if k:
        u = x & 0xFFFFFFFF
        b = [u & 255, (u >> 8) & 255, (u >> 16) & 255, (u >> 24) & 255]
        out += bytes(b[:k - 1])
    if len(out) < 6:
        raise ValueError('table data is too short')
    expect = out[0] | (out[1] << 8) | (out[2] << 16) | (out[3] << 24)
    raw = zlib.decompress(bytes(out[4:]))
    if len(raw) != expect:
        raise ValueError('table data has the wrong length (%d != %d)' % (len(raw), expect))
    return raw


# ---------------------------------------------------------------- 表解析

def _parse_rgb_table(raw):
    """解析 RGBTable（3D LUT）。返回 (div, lut, primaries, gamma)。"""
    if len(raw) < 16:
        raise ValueError('RGB table is truncated')
    typ = int.from_bytes(raw[0:4], 'little')
    dims = int.from_bytes(raw[8:12], 'little')
    div = int.from_bytes(raw[12:16], 'little')
    if typ != 1 or dims != 3:
        raise ValueError('RGB table type %d / dims %d not supported' % (typ, dims))
    if div < 2 or div > 128:
        raise ValueError('RGB table div %d not supported' % div)
    count = div * div * div * 3
    o = 16 + count * 2
    if len(raw) < o + 28:
        raise ValueError('RGB table is truncated')
    # 恒等索引（每个通道的基准值）
    ident = np.floor((np.arange(div) * 0xFFFF + (div >> 1)) / (div - 1)).astype(np.int32)
    # 读取 uint16 网格值，加 ident 后 /65535
    # 内存顺序：b 变化最快，r 最慢（参考实现的 for r/for g/for b 循环）
    vals = np.frombuffer(raw, dtype='<u2', count=count, offset=16).astype(np.int32)
    lut = np.empty(count, dtype=np.float64)
    idx = np.arange(div)
    # 第 k 个三元组对应 (r, g, b) = (k//div//div, k//div%div, k%div)
    rr = np.repeat(idx, div * div)          # r 最慢
    gg = np.tile(np.repeat(idx, div), div)  # g 次之
    bb = np.tile(idx, div * div)            # b 最快
    lut[0::3] = (vals[0::3] + ident[rr]) & 0xFFFF
    lut[1::3] = (vals[1::3] + ident[gg]) & 0xFFFF
    lut[2::3] = (vals[2::3] + ident[bb]) & 0xFFFF
    lut = lut / 65535.0
    prim = int.from_bytes(raw[o:o + 4], 'little')
    gam = int.from_bytes(raw[o + 4:o + 8], 'little')
    gamut = int.from_bytes(raw[o + 8:o + 12], 'little')
    primaries = {0: 'sRGB', 1: 'Adobe', 2: 'ProPhoto', 3: 'P3', 4: 'Rec2020'}.get(prim, str(prim))
    gamma = {0: 'linear', 1: 'sRGB', 2: '1.8', 3: '2.2', 4: 'Rec2020'}.get(gam, str(gam))
    if primaries != 'sRGB' or gamma != 'sRGB':
        raise ValueError('RGB table %s/%s not supported (only sRGB/sRGB)' % (primaries, gamma))
    return div, lut.reshape(div, div, div, 3), primaries, gamma


def _parse_look_table(raw):
    """解析 LookTable（HSV 表）。返回 (hd, sd, vd, encoding, data)。"""
    if len(raw) < 20:
        raise ValueError('look table is truncated')
    typ = int.from_bytes(raw[0:4], 'little')
    hd = int.from_bytes(raw[8:12], 'little')
    sd = int.from_bytes(raw[12:16], 'little')
    vd = int.from_bytes(raw[16:20], 'little')
    if typ != 0:
        raise ValueError('look table type %d not supported' % typ)
    if not (1 <= hd <= 360 and 2 <= sd <= 256 and 1 <= vd <= 256):
        raise ValueError('look table dims %dx%dx%d not supported' % (hd, sd, vd))
    count = hd * sd * vd * 3
    if len(raw) < 20 + count * 4:
        raise ValueError('look table is truncated')
    data = np.frombuffer(raw, dtype='<f4', count=count, offset=20).astype(np.float64)
    if not np.isfinite(data).all():
        raise ValueError('look table contains non-finite value')
    encoding = int.from_bytes(raw[20 + count * 4:24 + count * 4], 'little') if len(raw) >= 24 + count * 4 else 0
    if encoding not in (0, 1):
        raise ValueError('look table encoding %d not supported' % encoding)
    return hd, sd, vd, encoding, data.reshape(vd, hd, sd, 3)


# ---------------------------------------------------------------- XML 解析（轻量）

def _unescape_xml(s):
    if '&' not in s:
        return s
    import html
    return html.unescape(s)


def _parse_xmp_tree(text):
    """极简 XMP 解析：只提取 rdf:Description 的属性（crs:* 及其值）。"""
    # 提取所有 rdf:Description 的属性块（crs 命名空间的属性 + Table_* 内嵌值）
    result = []  # list of dict: {attr_name: value}
    # 匹配 <rdf:Description ...> 到 对应闭合 </rdf:Description>
    for m in re.finditer(r'<rdf:Description\b([^>]*)>(.*?)</rdf:Description>', text, re.S):
        attrs_str = m.group(1)
        inner = m.group(2)
        d = {}
        for am in re.finditer(r'([A-Za-z_][\w.\-]*(?::[A-Za-z_][\w.\-]*)?)\s*=\s*"([^"]*)"', attrs_str):
            name = am.group(1)
            val = _unescape_xml(am.group(2))
            d[name] = val
        # 子元素（text-only 的 crs:* 属性）
        for cm in re.finditer(r'<(crs:[A-Za-z_][\w.\-]*)\b[^>]*>([^<]*)</\1>', inner):
            d.setdefault(cm.group(1), _unescape_xml(cm.group(2)).strip())
        result.append(d)
    return result


# ---------------------------------------------------------------- 色彩空间

_S2P = np.array([
    [0.5293458246046687, 0.3300727901912129, 0.14058125375079608],
    [0.09837436211886709, 0.8734610448191785, 0.028164686612267942],
    [0.016883187456226075, 0.11767247216909364, 0.8654443038912419],
])
_P2S = np.array([
    [2.0340763610012553, -0.7273343315490479, -0.30674170521474897],
    [-0.228813409595274, 1.231730168456554, -0.0029169042747250254],
    [-0.008569763411926157, -0.15328659684761936, 1.1618564158615476],
])

# Adobe Standard base tone 曲线模型的 9 个参数（10 均匀节点上 9 段增量的对数）
_TONE_PARAMS = np.array([
    -3.8522722485313823, -4.2799445760722135, -3.747808726352907,
    -3.630660746401849, -2.3603584555646804, -3.2903485727174924,
    -1.4612313304803706, -6.0889513506678385, -5.086922596813801,
])


def _srgb_to_lin(v):
    v = np.clip(v, 0, 1)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def _lin_to_srgb(v):
    v = np.clip(v, 0, 1)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * (v ** (1 / 2.4)) - 0.055)


def _pchip_build(xs, ys):
    """PCHIP（保形三次 Hermite）插值，返回 callable。"""
    from scipy.interpolate import PchipInterpolator
    return PchipInterpolator(xs, ys)


def _tone_curve():
    """构造 Adobe Standard base tone 曲线（display <-> linear ProPhoto pre-tone）。"""
    KX = np.linspace(0, 1, 10)
    y = np.zeros(10)
    acc = 0.0
    for i in range(9):
        acc += np.exp(_TONE_PARAMS[i])
        y[i + 1] = acc
    top = y[9]
    fwd = _pchip_build(KX, y)
    # 反函数：4097 点表 + 单调最大
    xs = np.linspace(0, 1, 4097)
    ys = np.array([fwd(x) for x in xs])
    ys = np.maximum.accumulate(ys)
    return fwd, xs, ys, top


def _rgb_tone(rgb, f):
    """保色相曲线（DNG RefBaselineRGBTone）：映射最大/最小通道，中间通道保持相对位置。"""
    out = rgb.copy()
    for i in range(rgb.shape[0]):
        r, g, b = rgb[i]
        # 稳定排序（值相同时前面的算小）
        vals = [r, g, b]
        order = sorted(range(3), key=lambda j: vals[j])
        lo, mid, hi = order[0], order[1], order[2]
        mn, mx = vals[lo], vals[hi]
        md = vals[mid]
        fmx, fmn = f(mx), f(mn)
        d = mx - mn
        t = (md - mn) / d if d > 1e-9 else 0.0
        out[i, lo] = fmn
        out[i, mid] = fmn + (fmx - fmn) * t
        out[i, hi] = fmx
    return out


def _apply_look_table(pp, hd, sd, vd, encoding, data):
    """对线性 ProPhoto 三元组应用 HSV LookTable。"""
    r = np.clip(pp[:, 0], 0, 1)
    g = np.clip(pp[:, 1], 0, 1)
    b = np.clip(pp[:, 2], 0, 1)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    c = mx - mn
    # hue (0..6)
    h = np.zeros_like(r)
    mask = c > 1e-12
    cm = c[mask]
    rm, gm, bm = r[mask], g[mask], b[mask]
    mxm = mx[mask]
    htmp = np.where(mxm == rm, ((gm - bm) / cm) % 6.0,
                    np.where(mxm == gm, (bm - rm) / cm + 2, (rm - gm) / cm + 4))
    h[mask] = htmp
    s = np.where(mx > 1e-12, c / mx, 0.0)
    v = mx
    ve = _lin_to_srgb(v) if encoding == 1 else v
    # 表查找（三线性，色相环绕，饱和度/明度 clamp）
    hi = (h / 6.0) * hd
    si = s * (sd - 1)
    vi = ve * (vd - 1)
    hf = np.floor(hi).astype(np.int64)
    h0 = hf % hd
    h1 = (h0 + 1) % hd
    fh = hi - hf
    s0 = np.clip(np.floor(si).astype(np.int64), 0, sd - 2)
    fs = si - s0
    v0 = np.zeros_like(vi, dtype=np.int64)
    v1 = v0.copy()
    fv = np.zeros_like(vi)
    if vd > 1:
        v0 = np.clip(np.floor(vi).astype(np.int64), 0, vd - 2)
        v1 = v0 + 1
        fv = vi - v0
    # 累加 8 个顶点
    acc = np.zeros((pp.shape[0], 3))
    for a in (0, 1):
        va = v1 if a else v0
        wa = fv if a else (1 - fv)
        for bb in (0, 1):
            hb = h1 if bb else h0
            wb = fh if bb else (1 - fh)
            wab = wa * wb
            # 顶点数据: data[va, hb, s0] 和 data[va, hb, s0+1]
            d0 = data[va, hb, s0]   # (N,3)
            d1 = data[va, hb, s0 + 1]
            acc += (wab * (1 - fs))[:, None] * d0
            acc += (wab * fs)[:, None] * d1
    # hsv -> rgb（用偏移后的色相 + 缩放后的饱和度/明度）
    h2 = (h + acc[:, 0] / 60.0) % 6.0
    s2 = np.clip(s * acc[:, 1], 0, 1)
    v2 = np.clip(v * acc[:, 2], 0, 1)
    fl = np.floor(h2).astype(np.int64)
    sector = fl % 6
    f = h2 - fl
    p = v2 * (1 - s2)
    q = v2 * (1 - s2 * f)
    t = v2 * (1 - s2 * (1 - f))
    out = np.empty_like(pp)
    out[:, 0] = np.where(sector == 0, v2, np.where(sector == 1, q, np.where(sector == 2, p, np.where(sector == 3, p, np.where(sector == 4, t, v2)))))
    out[:, 1] = np.where(sector == 0, t, np.where(sector == 1, v2, np.where(sector == 2, v2, np.where(sector == 3, q, np.where(sector == 4, p, p)))))
    out[:, 2] = np.where(sector == 0, p, np.where(sector == 1, p, np.where(sector == 2, t, np.where(sector == 3, v2, np.where(sector == 4, v2, q)))))
    return out


def _apply_rgb_table(lut, div, rgb):
    """对 sRGB 0..1 三元组应用 RGBTable（三线性）。"""
    grid = np.linspace(0, 1, div)
    out = np.empty_like(rgb)
    for c in range(3):
        x = rgb[:, c]
        k = np.searchsorted(grid, x, side='right') - 1
        k = np.clip(k, 0, div - 2)
        frac = (x - grid[k]) / (grid[k + 1] - grid[k])
        # 三线性（此处仅对单通道需要完整 3D，用 scipy 更稳）
        idx = np.clip(np.searchsorted(grid, rgb, side='right') - 1, 0, div - 2)
    # 用 scipy RegularGridInterpolator 更简洁稳健
    from scipy.interpolate import RegularGridInterpolator
    interp = RegularGridInterpolator((grid, grid, grid), lut, method='linear', bounds_error=False, fill_value=None)
    res = interp(rgb)
    return np.clip(res, 0, 1)


# ---------------------------------------------------------------- 主入口

def _read_curves(descs, keys):
    """从 rdf:Description 列表读 ToneCurvePV2012 曲线点。返回 {master/red/green/blue: [(x,y)...] 或 None}。"""
    curves = {'master': None, 'red': None, 'green': None, 'blue': None}
    key_map = {'master': 'ToneCurvePV2012', 'red': 'ToneCurvePV2012Red',
               'green': 'ToneCurvePV2012Green', 'blue': 'ToneCurvePV2012Blue'}
    for d in descs:
        for slot, key in key_map.items():
            if curves[slot] is not None:
                continue
            # crs:ToneCurvePV2012 以 rdf:Seq 子元素存储
            v = d.get('crs:' + key)
            if v is None:
                continue
            pts = []
            for part in v.split(','):
                part = part.strip()
                if not part:
                    continue
                # 曲线点存成 "0, 0" 对，但 rdf:li 每个是单独 "x, y"
                pass
            # 上面的简单属性不适用，曲线是结构化 rdf:Seq，需从原始文本取
    return curves


def xmp_to_lut(xmp_path, size=64):
    """把 .xmp Look 预设转成 (size,size,size,3) 的 3D LUT（sRGB 0..1 -> sRGB 0..1）。

    返回 dict: {'lut': ndarray, 'title': str, 'rgb_div': int|None, 'look_dims': tuple|None,
                'curves': dict, 'unsupported': [str]}
    """
    text = open(xmp_path, encoding='utf-8', errors='ignore').read()
    if text.startswith('\ufeff'):
        text = text[1:]

    # 1) 解析 rdf:Description 属性
    descs = _parse_xmp_tree(text)
    if not descs:
        raise ValueError('no rdf:Description in XMP')

    # 顶层 bag（所有 Description 的 crs 属性合并）
    top = {}
    for d in descs:
        for k, v in d.items():
            if k.startswith('crs:') and k not in top:
                top[k] = v
            elif k.startswith('Table_') and k not in top:
                top[k] = v
    # 也收集非 crs 的 Table_*（内嵌表可能在任何 Description）
    for d in descs:
        for k, v in d.items():
            if k.startswith('Table_') and k not in top:
                top[k] = v

    # 2) 找 LookTable / RGBTable 引用
    rgb_id = (top.get('crs:RGBTable') or '').strip()
    look_id = (top.get('crs:LookTable') or '').strip()

    rgb_text = None
    look_text = None
    # Table_ 可能存为 'Table_<UUID>'（前缀可能带 crs: 或裸）
    for key in top:
        for base, uuid in (('Table_', rgb_id), ('Table_', look_id)):
            if not uuid:
                continue
            if key.endswith(base + uuid) or key == base + uuid or key == 'crs:' + base + uuid:
                val = top[key].strip()
                if val:
                    if uuid == rgb_id:
                        rgb_text = val
                    else:
                        look_text = val

    rgb_table = _parse_rgb_table(_decode_table_text(rgb_text)) if rgb_text else None
    look_table = _parse_look_table(_decode_table_text(look_text)) if look_text else None

    if rgb_table is None and look_table is None:
        raise ValueError('no RGBTable or LookTable found in XMP (this is not a Look preset)')

    # 3) 读取曲线（从原始文本直接解析 ToneCurvePV2012 的 rdf:Seq）
    curves = _read_tone_curves_raw(text)

    # 4) 构建渲染模型并应用到 size^3 恒等网格
    lut = _render_look(size, rgb_table, look_table, curves)

    title = top.get('crs:Cluster', '') or 'XMP Look'

    return {
        'lut': lut,
        'title': title,
        'rgb_div': rgb_table[0] if rgb_table else None,
        'look_dims': (look_table[0], look_table[1], look_table[2]) if look_table else None,
        'curves': {k: (len(v) if v else 0) for k, v in curves.items()},
    }


def _read_tone_curves_raw(text):
    """从原始 XMP 文本解析 ToneCurvePV2012(+Red/Green/Blue) 的曲线点。

    Lightroom 存成 <crs:ToneCurvePV2012><rdf:Seq><rdf:li>0, 0</rdf:li>...</rdf:Seq></crs:...>
    """
    curves = {'master': None, 'red': None, 'green': None, 'blue': None}
    key_map = {'master': 'ToneCurvePV2012', 'red': 'ToneCurvePV2012Red',
               'green': 'ToneCurvePV2012Green', 'blue': 'ToneCurvePV2012Blue'}
    for slot, key in key_map.items():
        # 匹配 <crs:KEY> ... </crs:KEY> 内部所有 <rdf:li>x, y</rdf:li>
        m = re.search(r'<crs:%s\b[^>]*>(.*?)</crs:%s>' % (re.escape(key), re.escape(key)), text, re.S)
        if not m:
            continue
        pts = []
        for li in re.finditer(r'<rdf:li[^>]*>\s*([^<]*?)\s*</rdf:li>', m.group(1)):
            val = li.group(1).strip()
            parts = val.split(',')
            if len(parts) != 2:
                continue
            try:
                x, y = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            if pts and x <= pts[-1][0]:
                continue
            pts.append((x, y))
        if len(pts) >= 2:
            curves[slot] = pts
    return curves


def _render_look(size, rgb_table, look_table, curves):
    """把 Look 渲染到 size^3 的 sRGB 恒等网格，输出 (size,size,size,3) LUT。

    严格复刻 acrlook/acrsim 的渲染管线（GRMod look.ts 的语义）：
      display(sRGB) -> [lookTable: toPre -> applyLookTable -> toDisplay]
                    -> point curves (保色相, display-encoded ProPhoto)
                    -> RGBTable (三线性)
    """
    # 恒等输入网格（sRGB 编码 0..1）
    idx = np.arange(size, dtype=np.float64) / (size - 1)
    r, g, b = np.meshgrid(idx, idx, idx, indexing='ij')
    rgb = np.stack([r.ravel(), g.ravel(), b.ravel()], axis=1)  # (N,3)

    tone_fwd, tone_xs, tone_ys, tone_top = _tone_curve()

    def fwd_fn(v):
        # base tone 曲线：display 值 -> pre-tone 线性值（pchipEval(f, clip(v,0,1))）
        return np.clip(tone_fwd(np.clip(v, 0, 1)), 0, None)

    def inv_fn(v):
        # 反 base tone：pre-tone 线性值 -> display 值（interp(v, ys, xs)）
        vc = np.clip(v, 0, tone_top)
        return np.clip(np.interp(vc, tone_ys, tone_xs), 0, 1)

    def to_pre(d):
        # display(sRGB) -> pre-tone 线性 ProPhoto 值
        #   srgbToLin -> S2P 矩阵 -> linToSrgb -> rgbtone(fwd)
        # GRMod 行主序语义：out = in @ S2P（行向量右乘矩阵，无需转置）
        lin = _srgb_to_lin(d)
        pp = lin @ _S2P
        pp = _lin_to_srgb(pp)
        return _rgb_tone(pp, fwd_fn)

    def to_display(pre):
        # pre-tone 线性 ProPhoto 值 -> display(sRGB)
        #   clip 到 top -> rgbtone(inv) -> srgbToLin -> P2S 矩阵 -> linToSrgb
        d = np.clip(pre, 0, tone_top)
        d = _rgb_tone(d, inv_fn)
        lin = _srgb_to_lin(d)
        return _lin_to_srgb(lin @ _P2S)

    d = np.clip(rgb, 0, 1).copy()

    # LookTable 阶段
    if look_table is not None:
        hd, sd, vd, encoding, data = look_table
        pre = to_pre(d)
        pre = _apply_look_table(pre, hd, sd, vd, encoding, data)
        d = to_display(pre)

    # point curve 阶段（保色相，display-encoded ProPhoto）
    # 先转 ProPhoto 编码，应用曲线，再转回
    lin = _srgb_to_lin(d)
    pp = _lin_to_srgb(lin @ _S2P)
    # 预构建曲线函数
    curve_fns = {}
    for slot in ('master', 'red', 'green', 'blue'):
        pts = curves.get(slot)
        if not pts:
            continue
        xs = np.array([p[0] / 255.0 for p in pts])
        ys = np.array([p[1] / 255.0 for p in pts])
        if len(pts) > 2:
            from scipy.interpolate import PchipInterpolator
            curve_fns[slot] = PchipInterpolator(xs, ys)
        else:
            curve_fns[slot] = lambda v, xs=xs, ys=ys: np.interp(v, xs, ys)
    if 'master' in curve_fns:
        fm = curve_fns['master']
        pp = _rgb_tone(pp, lambda v: np.clip(fm(np.clip(v, 0, 1)), 0, 1))
    for ci, slot in ((0, 'red'), (1, 'green'), (2, 'blue')):
        if slot in curve_fns:
            f = curve_fns[slot]
            pp[:, ci] = np.clip(f(np.clip(pp[:, ci], 0, 1)), 0, 1)
    d = _lin_to_srgb(_srgb_to_lin(pp) @ _P2S)

    # RGBTable 阶段（三线性）
    if rgb_table is not None:
        div, lut, _, _ = rgb_table
        d = _apply_rgb_table(lut, div, d)

    return np.clip(d, 0, 1).reshape(size, size, size, 3)
