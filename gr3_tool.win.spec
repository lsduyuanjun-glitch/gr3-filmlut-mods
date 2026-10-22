# -*- mode: python ; coding: utf-8 -*-
"""GR3 胶片固件工具 —— macOS 原生 .app 打包配置。

用法：
    pyinstaller gr3_tool.spec --noconfirm

产物：dist/GR3胶片工具.app（双击即用，无需安装 Python）
      dist/GR3胶片工具.zip（发给用户的分发包）

设计要点
--------
1. BUNDLE 模式：产出标准 macOS .app，双击启动、Dock 有图标、无终端窗口。
2. 只带必需资源：引擎 .py + work 拟合数据 + third_party 编解码器 + index.html。
   官方固件（30MB）**不随包分发**（理光不允许转发），由用户在运行时放入；
   程序会自动在 用户目录 / 桌面 / 下载 里找 fwdc239b.bin。
3. 可写数据不落包内：胶片库、解锁状态、生成的固件都写到
   ~/Library/Application Support/GR3FilmTool/（由 paths.py 决定）。
4. 显式排除重型无关库：只依赖 numpy/scipy/Pillow/colour-science/tifffile/
   capstone/unicorn，其余全部排除，避免把环境里的 torch 之类拖进来（体积从 1GB 降到 ~100MB）。
"""
import os

# SPECPATH 在 PyInstaller 中就是 spec 文件所在**目录**（字符串），
# 旧写法套 dirname 会指到仓库上一层 → os.listdir 收集引擎 .py 全部落空
# （CI 打包版启动即缺引擎脚本 / index.html，报「index.html 未找到」）。
REPO = os.path.abspath(SPECPATH)
if not os.path.isfile(os.path.join(REPO, 'gr3_tool.win.spec')):
    REPO = os.path.dirname(REPO)  # 兜底：万一未来 SPECPATH 传的是文件路径
WEBTOOL = os.path.join(REPO, 'webtool')

# —— 打包前自检（防回归）—————————————————————————————————
# 历史上因 REPO 多套一层目录，导致引擎 .py / index.html 全没进包，
# 产出的 CI 包启动即报「index.html 未找到」。这里在真正打包前先断言关键文件存在，
# 任一缺失就中止构建（exit 2），绝不让坏包有机会被发布。
def _build_guard():
    import sys as _sys
    critical = [
        (os.path.join(WEBTOOL, 'index.html'), '前端 index.html'),
        (os.path.join(REPO, 'make_slots15.py'), '引擎 make_slots15.py'),
        (os.path.join(REPO, 'armasm.py'), '引擎 armasm.py'),
        (os.path.join(WEBTOOL, 'paths.py'), '后端 paths.py'),
        (os.path.join(WEBTOOL, 'app.py'), 'macOS 入口 app.py'),
        (os.path.join(WEBTOOL, 'server.py'), 'Windows 入口 server.py'),
    ]
    missing = [label for p, label in critical if not os.path.exists(p)]
    if missing:
        _sys.stderr.write(
            "\n[BUILD FATAL] 资源根判断可能有误，以下关键文件缺失：\n  - "
            + "\n  - ".join(missing) + "\n"
            "  REPO    = " + REPO + "\n"
            "  WEBTOOL = " + WEBTOOL + "\n"
            "  若是历史 bug（REPO 多套一层目录），请修正 SPECPATH 处理。\n"
            "  已中止打包，避免产出坏包。\n"
        )
        _sys.exit(2)

_build_guard()

# ————————————————————————————————————————————————
# 数据文件（相对 REPO，打包后平铺到 _internal 根，使 RESOURCE_DIR == _internal）
# ————————————————————————————————————————————————
datas = [
    # 拟合数据：v16 是构建用的（含 hue_q10）；v11 供「新建胶片」的灰轴检查等引用
    ('work/films_v16/fits', 'work/films_v16/fits'),
    ('work/films_v11/fits', 'work/films_v11/fits'),
    # v16 构建必需：GR IV MultiAxial 标准数据（33 字节，但缺了会 KeyError）
    ('work/ma_probe5/gr4_std_ma.json', 'work/ma_probe5'),
    # cube_fit 的基准 gamma 表（构建与新建胶片都要用）
    ('work/base_gamma_std.npy', 'work'),
    # gr4_editor 固件容器编解码器（GPL-2.0，第三方子模块）
    ('third_party/gr-custom-tool', 'third_party/gr-custom-tool'),
    # 前端
    ('webtool/index.html', '.'),
]

# 引擎脚本：仓库根的全部 .py（make_slots15/16、make_grain_native、gr3patch、
# film_cave、armasm、raw_nr、cube_fit/joint_fit/lab_fit、xmp_reader、codec_path、
# gr3_tmp 等），全部平铺到根目录：
#   codec_path.py / gr3_tmp.py 靠 __file__ 定位同目录依赖，平铺后路径推导才成立
# 跳过：以 . 或 _ 开头的（下划线是本地诊断/测试脚本，不随包分发）
for f in sorted(os.listdir(REPO)):
    if f.endswith('.py') and not f.startswith(('.', '_')) and f != 'server.py':
        datas.append((f, '.'))

for f in ('build_firmware.py', 'film_library.py', 'license.py', 'paths.py'):
    datas.append((os.path.join('webtool', f), '.'))

# 初始胶片库（首次运行时播种到用户目录）
datas.append(('film_library.json', '.'))

# ————————————————————————————————————————————————
# 隐式导入（动态 import 的模块，静态分析抓不到）
# ————————————————————————————————————————————————
hiddenimports = [
    # 引擎
    'make_slots15', 'make_slots16', 'make_grain', 'make_grain_native',
    'gr3patch', 'make_film', 'film_cave', 'armasm', 'raw_nr',
    'make_icons', 'make_icons_custom', 'codec_path', 'gr3_tmp',
    'emu', 'fw', 'run_tuning', 'verify_slots16',
    # 网页后端
    'film_pipeline', 'film_library', 'license', 'build_firmware', 'paths',
    # 付费解锁 ed25519 验签（license.py 惰性 import，静态分析抓不到；漏掉=解锁崩溃）
    'cryptography', 'cryptography.hazmat.primitives.asymmetric.ed25519',
    'cube_fit', 'joint_fit', 'lab_fit', 'xmp_reader', 'xmp2cube',
    # 第三方编解码器（gr4_editor 由 codec_path 运行时加 sys.path，
    # 但这里显式列出核心模块，确保 PyInstaller 收集到）
    'gr4_editor', 'gr4_editor.codec', 'gr4_editor.codec.container',
    'gr4_editor.codec.frames', 'gr4_editor.firmware',
    # 科学计算
    'numpy', 'scipy', 'scipy.interpolate', 'scipy.linalg', 'scipy.optimize',
    'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont',
    'tifffile', 'colour',
    # 反汇编 / 模拟（verify 用）
    'capstone', 'unicorn', 'unicorn.arm_const', 'unicorn.arm64_const',
]

# ————————————————————————————————————————————————
# 显式排除（体积控制的唯一有效手段：把环境里的重型无关库全挡掉）
# ————————————————————————————————————————————————
excludes = [
    'tkinter', 'matplotlib', 'pandas', 'IPython', 'jupyter', 'notebook',
    # 注意：不要排除 distutils / unittest —— PyInstaller 自带 hook-distutils.py
    # 会为其建立别名，若在此排除会抛
    #   ValueError: Target module "distutils" already imported as ExcludedModule
    # 它们是 stdlib/轻量，留着无体积代价。
    # 这些是被打包环境「误带」进来的元凶，本工具完全不需要
    'transformers', 'tokenizers', 'transformers_stream_generator',
    'funasr', 'modelscope', 'torch', 'torchvision', 'torchaudio',
    'onnx', 'onnxruntime', 'paddle', 'paddlepaddle',
    'datasets', 'huggingface_hub', 'accelerate', 'safetensors', 'hf_xet',
    'librosa', 'soundfile', 'webrtcvad',
    'sklearn', 'scikit-learn', 'networkx', 'sympy',
    'av', 'cv2', 'numba', 'llvmlite',
    'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'wx',
    'boto3', 'botocore', 's3transfer', 'google', 'googleapiclient',
    # 注意：cryptography 故意不排除！license.py 的 ed25519 验签依赖它
    # （Mac 版靠启动器调用独立 python 运行时才没暴露此问题；Windows 冻结版必须自带）。
    'bcrypt', 'paramiko', 'nacl',
    'fastapi', 'uvicorn', 'starlette', 'pydantic', 'sqlalchemy', 'alembic',
    'jinja2', 'anyio', 'httpx', 'aiohttp', 'requests', 'urllib3',
    'yaml', 'ruamel', 'lxml', 'bs4', 'html5lib',
    'IPython', 'pygments', 'jedi', 'parso',
]

a = Analysis(
    [os.path.join('webtool', 'server.py')],
    pathex=[REPO, WEBTOOL, os.path.join(REPO, 'third_party', 'gr-custom-tool')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GR3FilmTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,           # Windows 首版保留黑色终端窗口，便于排查报错；稳定后可改 False
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='GR3FilmTool',
)
