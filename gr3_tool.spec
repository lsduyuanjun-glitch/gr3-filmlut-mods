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
import os, sys

# —— 构建环境自举：原生窗口壳（pywebview + PyObjC）缺失时现场安装 ——
# spec 在 CI 的裸 Python 环境里执行，hiddenimports 需要这些包真实存在。
# 在 spec 里自举就不必改动 CI workflow（改 .github/ 需要 token 有 workflow 权限）。
def _ensure_native_window_deps():
    try:
        import webview  # noqa: F401
        import objc  # noqa: F401
        return
    except ImportError:
        pass
    import subprocess
    print('[spec] installing native-window dependencies (pywebview + pyobjc)...')
    subprocess.check_call([sys.executable, '-m', 'pip', 'install',
                           'pywebview', 'pyobjc', 'bottle', 'proxy_tools'])

if sys.platform == 'darwin':
    _ensure_native_window_deps()

# SPECPATH 在 PyInstaller 中就是 spec 文件所在**目录**（字符串），
# 旧写法 dirname(dirname) 会指到仓库上一层 → 循环收集引擎 .py 全部落空（打包版启动即 ModuleNotFoundError）。
REPO = os.path.abspath(SPECPATH)
if not os.path.isfile(os.path.join(REPO, 'gr3_tool.spec')):
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
        (os.path.join(REPO, 'armmini.py'), '内置 ARM 汇编器 armmini.py'),
        (os.path.join(REPO, 'verify_slots16.py'), '核验 verify_slots16.py'),
        (os.path.join(REPO, 'emu.py'), '核验仿真 emu.py'),
        (os.path.join(REPO, 'fw.py'), '核验底版加载 fw.py'),
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
    if f.endswith('.py') and not f.startswith(('.', '_')) and f != 'app.py':
        datas.append((f, '.'))

for f in ('build_firmware.py', 'film_library.py', 'license.py', 'paths.py', 'server.py'):
    datas.append((os.path.join('webtool', f), '.'))

# 初始胶片库（首次运行时播种到用户目录）
datas.append(('film_library.json', '.'))

# —— unicorn 原生库必须显式收集（v1.5.6）——
# unicorn 2.x 是纯 Python 绑定 + ctypes 加载 unicorn/lib/ 下的外置动态库
# （libunicorn.2.dylib）。PyInstaller 静态分析收不到 ctypes 外置库，
# v1.5.5 因此核验崩在「Failed to load the Unicorn dynamic library」。
# 这里按包内真实布局整体收进 datas（跳过 25MB 静态库 .a），运行时
# server.py 再用 LIBUNICORN_PATH 指向它。
def _collect_unicorn_lib():
    import glob
    import importlib.util
    import sys as _sys
    sp = importlib.util.find_spec('unicorn')
    if sp is None or sp.origin is None:
        _sys.stderr.write(
            "\n[BUILD FATAL] 构建环境未安装 unicorn（pip install unicorn==2.1.4）。\n"
            "  缺它核验链在冻结版必崩。已中止打包。\n")
        _sys.exit(2)
    lib_dir = os.path.join(os.path.dirname(os.path.abspath(sp.origin)), 'lib')
    files = [(p, os.path.join('unicorn', 'lib'))
             for p in sorted(glob.glob(os.path.join(lib_dir, '*')))
             if os.path.isfile(p) and not p.endswith('.a')]
    if not files:
        _sys.stderr.write(
            "\n[BUILD FATAL] unicorn 包里没找到原生库：%s\n  已中止打包。\n" % lib_dir)
        _sys.exit(2)
    return files

datas += _collect_unicorn_lib()

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
    # 付费解锁 ed25519 验签（license.py 惰性 import，静态分析抓不到）
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
    # unicorn 2.x 的 arch 子模块按 arch 名**动态 import**，静态分析抓不到，
    # 冻结版缺它报 No module named 'unicorn.unicorn_py3.arch.arm'（v1.5.6 实测）
    'unicorn.unicorn_py3', 'unicorn.unicorn_py3.unicorn',
    'unicorn.unicorn_py3.arch', 'unicorn.unicorn_py3.arch.types',
    'unicorn.unicorn_py3.arch.arm', 'unicorn.unicorn_py3.arch.arm64',
    'unicorn.unicorn_py3.arch.intel',
    # 原生窗口壳（PyWebview + PyObjC 的 Cocoa/WebKit 后端）
    'webview', 'webview.platforms.cocoa', 'webview.http',
    'bottle', 'proxy_tools',
    'objc', 'PyObjCTools', 'PyObjCTools.AppHelper',
    'Cocoa', 'WebKit', 'Quartz', 'Security', 'UniformTypeIdentifiers',
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
    'bcrypt', 'paramiko', 'nacl',
    'fastapi', 'uvicorn', 'starlette', 'pydantic', 'sqlalchemy', 'alembic',
    'jinja2', 'anyio', 'httpx', 'aiohttp', 'requests', 'urllib3',
    'yaml', 'ruamel', 'lxml', 'bs4', 'html5lib',
    'IPython', 'pygments', 'jedi', 'parso',
]

a = Analysis(
    [os.path.join('webtool', 'app.py')],
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
    name='GR3胶片工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 无终端窗口
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

app = BUNDLE(
    coll,
    name='GR3胶片工具.app',
    icon=None,
    bundle_identifier='com.duccio.gr3filmtool',
    version='1.0.0',
    info_plist={
        'CFBundleName': 'GR3胶片工具',
        'CFBundleDisplayName': 'GR3 胶片滤镜工具',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
        # 说明这是本地工具、无网络行为，减少 Gatekeeper 的疑问
        'LSApplicationCategoryType': 'public.app-category.photography',
        'NSHumanReadableCopyright': 'GR3 Film Filter Tool',
    },
)
