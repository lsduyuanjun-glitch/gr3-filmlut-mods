#!/usr/bin/env python3
"""GR3 胶片滤镜工具后端 v16 —— 封装 gr3-film-mods 的 make_slots16 逻辑（作者 v16 完整管线）。

关键升级（相对旧 v11/v12 的 make_films10）：
  - 胶片作为「新增影像控制项」（tone 25+）追加到菜单末尾，不覆盖任何官方模式
  - 12 分区色相（MultiAxial hue sectors）：每个胶片带 hue_q10（12×3×3），
    启用机内 12 分区色相校正能力（GR III 默认关闭，GR IV 控制值启用）
  - RAW 显影兼容：RAW 回放可对胶片做影像控制
  - 官方模式（标准/正片/负片/黑白系）逐字节保留

用法：
  python build_firmware.py <官方固件.bin> <输出.bin> [--slot cross=duccio5219 ...]（旧参数兼容，实际按胶片表顺序）

返回 JSON 摘要。

注意：v16 模型是「新增影像控制项」，胶片追加在菜单末尾（第 12 格之后），
不是替换第 8-11 格。菜单顺序由 FILMS_ORDER 决定。
"""
import sys, os, json, hashlib

# —— 可移植路径解析：引擎代码放本目录 engine/，工具目录可整体移动 ——
_TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
def _resolve_repo():
    if os.environ.get('GR3_REPO'):
        return os.environ['GR3_REPO']
    bundled = os.path.join(_TOOL_DIR, 'engine')
    if os.path.isdir(bundled) and os.path.exists(os.path.join(bundled, 'make_slots15.py')):
        return bundled
    for up in (3, 4, 2):
        dev = os.path.abspath(os.path.join(_TOOL_DIR, *(['..'] * up), 'gr3-film-mods'))
        if os.path.isdir(dev) and os.path.exists(os.path.join(dev, 'make_slots15.py')):
            return dev
    return bundled

REPO = _resolve_repo()
sys.path.insert(0, REPO)

# 胶片 key → v16 fit JSON 路径（含 hue_q10）—— 最终 4 款（英泽君基底 + 特性校准）
FILMS = {
    'portra400':   'work/films_v16/fits/duccio/portra400.json',
    'ektar100':    'work/films_v16/fits/duccio/ektar100.json',
    '5207':        'work/films_v16/fits/duccio/5207.json',
    '5219':        'work/films_v16/fits/duccio/5219.json',
}

# 胶片 key → 机内显示名
FILM_NAME = {
    'portra400': 'Portra 400',
    'ektar100': 'Ektar 100',
    '5207': 'Kodak 5207',
    '5219': 'Kodak 5219',
}

# 菜单顺序（v16 追加顺序 = 菜单显示顺序，追加在官方 12 个模式之后）
# 默认：Portra 400 / Ektar 100 / Kodak 5207 / Kodak 5219
FILMS_ORDER = ['portra400', 'ektar100', '5207', '5219']


def load_film(name):
    path = os.path.join(REPO, FILMS[name])
    d = json.load(open(path))
    de = d.get('lab_fit', {}).get('after', {}).get('colorchecker',
         d.get('presets', [{}])[0].get('chart_de_mean', 0))
    return d, round(float(de), 2)


def main():
    args = sys.argv[1:]
    out_path = None
    in_path = None
    raw_nr_above = 8000  # 默认与作者 build.sh 一致
    grain = None  # 机内颗粒强度：0-8，None=不动（走相机菜单默认）
    grain_native = False  # 原生颗粒引擎（Particle，作者 v27-v30 路线）
    i = 0
    films_order = list(FILMS_ORDER)
    while i < len(args):
        a = args[i]
        if a == '--raw-nr-above':
            raw_nr_above = int(args[i + 1]); i += 2
        elif a == '--films':
            # v16 新增槽位顺序（逗号分隔 key），顺序即机内菜单显示顺序
            films_order = [k.strip() for k in args[i + 1].split(',') if k.strip()]
            i += 2
        elif a == '--grain':
            # 机内颗粒强度（strength×type 双档拉满到同一值，0-8）
            grain = int(args[i + 1]); i += 2
        elif a == '--grain-native':
            # 原生颗粒引擎（Particle，胶片复用机内「颗粒效果」菜单）
            grain_native = True; i += 1
        elif a == '--slot':
            # 旧参数兼容：v16 不按槽位替换，忽略
            i += 2
        elif a in ('--icon', '--label'):
            # v16 管线暂不支持自定义图标 / 机内名，忽略旧参数
            i += 2
        elif in_path is None:
            in_path = a; i += 1
        elif out_path is None:
            out_path = a; i += 1
        else:
            i += 1

    if not in_path or not out_path:
        print(json.dumps({'error': '用法: build_firmware.py <官方.bin> <输出.bin>'}))
        sys.exit(1)

    # 先把输入/输出路径转成绝对路径，避免 os.chdir(REPO) 后相对路径失效
    in_path = os.path.abspath(in_path)
    out_path = os.path.abspath(out_path)

    os.chdir(REPO)
    import make_slots15 as M15
    import make_slots16 as M16

    # 校验固件 SHA
    sha = hashlib.sha256(open(in_path, 'rb').read()).hexdigest()
    expected = 'd6a3c9c288d784080e7b283222ecdd8752adfeed6faa36dab44f73115354bfd4'
    if sha != expected:
        print(json.dumps({'error': f'固件不匹配！期望 GR III 2.10 (fwdc239b.bin)，实际 SHA {sha[:16]}...'}))
        sys.exit(1)

    # 构造 films 列表：(key, display_name, fit, replaced_stock_tone_or_None)
    # 注意：display_name 必须用 make_slots15.FILMS[key]（英文菜单名），
    # 因为 verify_slots16 校验 string getter 时按 M.FILMS[key] 比对，
    # 且机内字符串表是 UTF-16LE，中文全角括号会导致校验失败。
    films = []
    summary = []
    for key in films_order:
        fit, de, film_cn = None, 0.0, key
        if key in FILMS:
            fit, de = load_film(key)
            film_cn = FILM_NAME.get(key, key)
        else:
            # 自建胶片：从胶片库取 fit 路径
            lib_path = os.path.join(REPO, 'film_library.json')
            if not os.path.exists(lib_path):
                print(json.dumps({'error': f'未知胶片 {key}（且无胶片库）'})); sys.exit(1)
            lib = json.load(open(lib_path))
            entry = lib.get('films', {}).get(key)
            if not entry:
                print(json.dumps({'error': f'未知胶片 {key}'})); sys.exit(1)
            fit = json.load(open(os.path.join(REPO, entry['fit'])))
            de = round(float(entry.get('de', 0)), 2)
            film_cn = entry.get('nick') or entry.get('name') or key
            # v16 需要 hue_q10（12 分区色相）；旧 v11 fit 缺它时注入中性恒等矩阵，向后兼容
            if 'hue_q10' not in fit:
                fit['hue_q10'] = [[[1024, 0, 0], [0, 1024, 0], [0, 0, 1024]] for _ in range(12)]
            # 自建胶片 key 动态注册进 M15 注册表（双保险；make_slots15._load_custom_films 已自动加载，
            # 这里确保 build 进程内 display_name = M15.FILMS[key] 一定取到值）
            M15.FILMS[key] = film_cn
            import re as _re
            _ascii = lambda _s: _re.sub(r'[^A-Za-z0-9]', '', _s or '')
            _cand = _ascii(entry.get('short')) or _ascii(film_cn) or _ascii(key) or 'CSTM'
            # 无专属图标 → 简单框 + 命名（ASCII 短码 + 暖灰中性色，与 make_slots15 一致）
            M15.ICON_LABELS[key] = (_cand[:4].upper(), (200, 190, 175))
        # display_name 必须用 make_slots15.FILMS[key]（verify 按 M.FILMS[key] 比对）
        display_name = M15.FILMS[key]
        films.append((key, display_name, fit, None))
        summary.append({'film': key, 'film_cn': film_cn, 'deltaE': de})

    # 执行 v16 patch（v15 新增影像控制项 + 12分区色相 + RAW显影兼容 + maker-note）
    from gr3patch import Image
    img = Image(in_path)
    # 原生颗粒菜单需要扩容 RTOS（grow 必须在任何 patch 之前，此时 decoded checksum 仍有效）
    if grain_native:
        img._grain_ext = img.grow(64 * 1024)
        img._grain_ext_cur = img._grain_ext
    info = M15.patch(img, films, raw_nr_above=raw_nr_above)
    info['_multiaxial'] = M16.patch_ma(img, films)
    info['_rawdev'] = M16.patch_rawdev(img, films, info)
    info['_exif_tone'] = M16.patch_exif_tone(img, films)

    # 原生颗粒引擎（Particle）：让胶片（tone 25+）复用机内「颗粒效果」菜单 + 启用 effect-stage
    # 这是作者 v27-v30 路线的逆向重实现（FINDINGS §45-48）。gate 修复(③)先接，①②随 make_grain_native 补全。
    if grain_native:
        import make_grain_native
        info['_grain_storage'] = make_grain_native.patch_storage(img, films, info)
        info['_grain_pipeline'] = make_grain_native.patch_pipeline(img, films, info)
        info['_grain_gate'] = make_grain_native.patch_gate(img, films, info)
        info['_grain_menu'] = make_grain_native.patch_menu(img, films, info)

    # 机内颗粒（strength × type 双档）：把理光机内颗粒拉满
    # 只 patch standard（4 款胶片走的模式），但为保险同时拉满全部 7 个模式
    if grain is not None:
        import make_grain
        grain_specs = {m: {'strength': grain, 'type': grain}
                       for m in make_grain.STRENGTH_ADDR}
        info['_grain'] = make_grain.patch_grain(img, grain_specs)

    data, rep = img.build()
    open(out_path, 'wb').write(data)

    changed = []
    for idx, (key, name, fit, repl) in enumerate(films):
        changed.append({
            'slot': key,
            'slot_cn': name,
            'film': key,
            'film_cn': FILM_NAME.get(key, name),
            'deltaE': summary[idx]['deltaE'],
            'camera_name': name,
            'tone': 25 + idx,
        })

    result = {
        'ok': True,
        'output': out_path,
        'output_size': len(data),
        'changed': changed,
        'slots': summary,
        'multiaxial': info.get('_multiaxial'),
        'rawdev': info.get('_rawdev'),
        'grain': info.get('_grain'),
        'grain_native': info.get('_grain_gate'),
        'grain_pipeline': info.get('_grain_pipeline'),
        'grain_storage': info.get('_grain_storage'),
        'grain_menu': info.get('_grain_menu'),
        'repack': rep,
        'warnings': [],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
