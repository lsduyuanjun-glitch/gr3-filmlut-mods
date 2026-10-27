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

import paths  # noqa: E402  (同目录；统一路径解析)
import models  # noqa: E402  (同目录；机型注册表)

# —— 路径解析 ——
# RESOURCE：只读资源（引擎 .py、work/ 拟合数据、third_party）
# USER_DIR：用户可写目录（胶片库、解锁状态、生成的固件）
_TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('GR3_REPO') or paths.RESOURCE_DIR
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(os.path.join(REPO, 'film_pipeline.py')))


def _abs_fit(path):
    """把胶片库里的 fit 路径解析成绝对路径。

    新胶片（打包后创建）存的是绝对路径；老胶片存的是相对仓库根的路径
    （如 work/films_v11/fits/xxx.json），需要拼到资源目录下。
    """
    if os.path.isabs(path):
        return path
    cand = os.path.join(REPO, path)
    if os.path.exists(cand):
        return cand
    return path

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


def build(in_path, out_path, films_order=None, raw_nr_above=8000,
          grain=None, grain_native=False, grain_fixed=None, grains=None,
          model='gr3'):
    """核心构建逻辑（可 import，供 server.py 进程内调用）。

    返回 result dict；出错时 raise（带明确信息）。不依赖 sys.argv / print / sys.exit。

    model: 机型 id（默认 'gr3'）。未支持机型会被 models.require_supported 直接拦截，
           绝不静默产出错误固件。
    """
    films_order = list(films_order or FILMS_ORDER)
    spec = models.require_supported(model)  # 闸门：未支持机型直接报错

    if not in_path or not out_path:
        raise ValueError('缺少输入/输出路径')

    # 先把输入/输出路径转成绝对路径，避免 os.chdir(REPO) 后相对路径失效
    in_path = os.path.abspath(in_path)
    out_path = os.path.abspath(out_path)

    prev_cwd = os.getcwd()
    os.chdir(REPO)
    try:
        import make_slots15 as M15
        import make_slots16 as M16
        # ★ 刷新自建胶片的机内名 / 胶卷盒配色 / 自定义图标：胶片库可能在会话中刚更新过
        #   （新建胶片、改图标），而 make_slots15 在首次 import 时只读了一次。
        M15._load_custom_films()

        # 校验固件 SHA（按机型查注册表，支持 GR III 全家族）
        sha = hashlib.sha256(open(in_path, 'rb').read()).hexdigest()
        if sha != spec.official_firmware_sha256:
            raise ValueError(
                f'固件不匹配！期望 {spec.display_name} {spec.official_firmware_version} '
                f'官方固件，实际 SHA {sha[:16]}...')

        # 构造 films 列表：(key, display_name, fit, replaced_stock_tone_or_None)
        films = []
        summary = []
        for key in films_order:
            fit, de, film_cn = None, 0.0, key
            if key in FILMS:
                fit, de = load_film(key)
                film_cn = FILM_NAME.get(key, key)
            else:
                # 自建胶片：从胶片库取 fit 路径（库在用户可写目录）
                lib_path = paths.LIB_PATH
                if not os.path.exists(lib_path):
                    raise ValueError(f'未知胶片 {key}（且无胶片库）')
                lib = json.load(open(lib_path, encoding='utf-8'))
                entry = lib.get('films', {}).get(key)
                if not entry:
                    raise ValueError(f'未知胶片 {key}')
                fit = json.load(open(_abs_fit(entry['fit']), encoding='utf-8'))
                de = round(float(entry.get('de', 0)), 2)
                film_cn = entry.get('nick') or entry.get('name') or key
                if 'hue_q10' not in fit:
                    fit['hue_q10'] = [[[1024, 0, 0], [0, 1024, 0], [0, 0, 1024]] for _ in range(12)]
                M15.FILMS[key] = film_cn
                import re as _re
                _ascii = lambda _s: _re.sub(r'[^A-Za-z0-9]', '', _s or '')
                _cand = _ascii(entry.get('short')) or _ascii(film_cn) or _ascii(key) or 'CSTM'
                M15.ICON_LABELS[key] = (_cand[:4].upper(), (200, 190, 175))
            display_name = M15.FILMS[key]
            films.append((key, display_name, fit, None))
            summary.append({'film': key, 'film_cn': film_cn, 'deltaE': de})

        # 执行 v16 patch
        from gr3patch import Image
        img = Image(in_path, model=model)
        if grain_native or grain_fixed is not None or grains is not None:
            img._grain_ext = img.grow(64 * 1024)
            img._grain_ext_cur = img._grain_ext
        info = M15.patch(img, films, raw_nr_above=raw_nr_above, model=model)
        info['_multiaxial'] = M16.patch_ma(img, films)
        info['_rawdev'] = M16.patch_rawdev(img, films, info)
        info['_exif_tone'] = M16.patch_exif_tone(img, films)

        if grains is not None:
            # 固件写死颗粒（逐槽位）：每槽位一个颗粒值，直出带颗粒，不需要机内设置
            import make_grain_native
            info['_grain_fixed'] = make_grain_native.patch_fixed_grain(img, films, info, grains)
        elif grain_fixed is not None:
            # 兼容旧单值：全部胶片同一个颗粒值（0=Off 1=High 2=Mid 3=Low）
            import make_grain_native
            info['_grain_fixed'] = make_grain_native.patch_fixed_grain(img, films, info, [grain_fixed] * len(films))
        elif grain_native:
            import make_grain_native
            info['_grain_storage'] = make_grain_native.patch_storage(img, films, info)
            info['_grain_pipeline'] = make_grain_native.patch_pipeline(img, films, info)
            info['_grain_gate'] = make_grain_native.patch_gate(img, films, info)
            info['_grain_menu'] = make_grain_native.patch_menu(img, films, info)

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
                'slot': key, 'slot_cn': name, 'film': key,
                'film_cn': FILM_NAME.get(key, name),
                'deltaE': summary[idx]['deltaE'],
                'camera_name': name, 'tone': 25 + idx,
            })

        return {
            'ok': True,
            'output': out_path,
            'output_size': len(data),
            'changed': changed,
            'slots': summary,
            'multiaxial': info.get('_multiaxial'),
            'rawdev': info.get('_rawdev'),
            'exif_tone': info.get('_exif_tone'),
            'grain': info.get('_grain'),
            'grain_native': info.get('_grain_gate'),
            'grain_fixed': info.get('_grain_fixed'),
            'grain_pipeline': info.get('_grain_pipeline'),
            'grain_storage': info.get('_grain_storage'),
            'grain_menu': info.get('_grain_menu'),
            'repack': rep,
            'warnings': [],
        }
    finally:
        os.chdir(prev_cwd)


def main():
    args = sys.argv[1:]
    out_path = None
    in_path = None
    raw_nr_above = 8000  # 默认与作者 build.sh 一致
    grain = None  # 机内颗粒强度：0-8，None=不动（走相机菜单默认）
    grain_native = False  # 原生颗粒引擎（Particle，作者 v27-v30 路线）
    grain_fixed = None  # 固件写死颗粒强度：1=High 2=Mid 3=Low，直出带颗粒，无需机内设置
    grains = None  # 固件写死颗粒（逐槽位）：逗号分隔，每槽位一个值（0=Off 1=High 2=Mid 3=Low）
    i = 0
    films_order = list(FILMS_ORDER)
    model = models.DEFAULT_MODEL  # 机型 id，默认 GR III
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
        elif a == '--grain-fixed':
            # 固件写死颗粒：1=High 2=Mid 3=Low，相机直出即带颗粒（无菜单设置）
            grain_fixed = int(args[i + 1]); i += 2
        elif a == '--grains':
            # 固件写死颗粒（逐槽位）：逗号分隔，如 "2,1,3,0" = Mid,High,Low,Off
            grains = [int(x.strip()) for x in args[i + 1].split(',') if x.strip() != '']
            i += 2
        elif a == '--slot':
            # 旧参数兼容：v16 不按槽位替换，忽略
            i += 2
        elif a == '--model':
            # 机型 id（gr3 / gr3x / gr3hdf / gr3xhdf）；未支持机型构建时会报错
            model = args[i + 1]; i += 2
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

    try:
        result = build(in_path, out_path, films_order=films_order,
                       raw_nr_above=raw_nr_above, grain=grain,
                       grain_native=grain_native, grain_fixed=grain_fixed,
                       grains=grains, model=model)
    except Exception as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
