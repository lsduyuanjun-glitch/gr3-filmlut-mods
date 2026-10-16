# -*- mode: python ; coding: utf-8 -*-
# GR3 胶片固件工具 macOS .app 打包配置
# 用法: pyinstaller gr3_tool.spec --noconfirm
# 产物: dist/GR3胶片工具.app  （onedir 模式，双击即用，无需装 Python）

import os

REPO = os.path.dirname(os.path.abspath(SPECPATH))  # 仓库根（gr3-film-mods）

# —— 需要作为数据打进包的文件/目录（相对仓库根）——
# 引擎数据（fit 拟合数据、cube、胶片库、第三方 gr4_editor 编解码器）
datas = [
    ('work/films_v16', 'work/films_v16'),
    ('work/films_v11', 'work/films_v11'),
    ('work/films', 'work/films'),
    ('work/films_v3', 'work/films_v3'),
    ('work/films_v4', 'work/films_v4'),
    ('work/duccio', 'work/duccio'),
    ('work/ma_probe5', 'work/ma_probe5'),
    ('third_party/gr-custom-tool', 'third_party/gr-custom-tool'),
    ('film_library.json', '.'),
]

# base_gamma_std.npy 若存在也带上
if os.path.exists(os.path.join(REPO, 'work', 'base_gamma_std.npy')):
    datas.append(('work/base_gamma_std.npy', 'work'))

# webtool 里的前端资源与脚本 —— 平铺到根目录（打包后 TOOL_DIR == REPO == _internal）
webtool_dir = os.path.join(REPO, 'webtool')
for fn in ('index.html', 'build_firmware.py', 'film_library.py', 'license.py'):
    datas.append((os.path.join('webtool', fn), '.'))

# 引擎根目录的所有 .py（make_slots15/16、make_grain_native、gr3patch、codec_path、film_pipeline 等）
# 平铺到根，保证子进程脚本 import 时能找到（codec_path.py 靠 __file__ 定位 third_party）
for f in os.listdir(REPO):
    if f.endswith('.py') and f not in ('server.py',):
        datas.append((f, '.'))

# —— 隐藏导入（PyInstaller 静态分析抓不到动态 import 的模块）——
# 注意：gr4_editor 靠 codec_path.py 在运行时动态加入 sys.path（third_party/gr-custom-tool），
# 不作为 hiddenimport 静态导入（会报 not found）；其源码作为 data 打包，运行时由 codec_path 加载。
hiddenimports = [
    'make_slots15', 'make_slots16', 'make_grain', 'make_grain_native',
    'gr3patch', 'make_film', 'film_cave', 'armasm', 'codec_path',
    'make_icons', 'make_icons_custom', 'emu', 'run_tuning',
    'film_pipeline', 'film_library', 'license', 'build_firmware',
    'capstone', 'unicorn', 'unicorn.arm_const', 'unicorn.arm64_const',
    'numpy', 'scipy', 'scipy.interpolate', 'scipy.linalg', 'scipy.optimize',
    'PIL', 'PIL.Image',
]

a = Analysis(
    [os.path.join('webtool', 'server.py')],
    pathex=[REPO, webtool_dir, os.path.join(REPO, 'third_party', 'gr-custom-tool')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'pandas', 'test',
        # 环境里被 funasr/modelscope 等无关库污染，PyInstaller 依赖扫描会误拖进来，全部排除
        'transformers', 'tokenizers', 'transformers_stream_generator',
        'funasr', 'modelscope', 'torch', 'torchvision', 'torchaudio',
        'onnx', 'onnxruntime', 'paddle', 'paddlepaddle',
        'datasets', 'huggingface_hub', 'accelerate', 'safetensors',
        'librosa', 'soundfile', 'webrtcvad',
        'sklearn', 'scikit-learn', 'networkx', 'sympy',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GR3胶片工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 无终端窗口（原生 .app 体验）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='GR3胶片工具',
)
