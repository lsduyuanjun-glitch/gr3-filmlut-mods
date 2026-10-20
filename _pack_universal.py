#!/usr/bin/env python3
"""GR3 胶片工具 —— Universal（双芯片通用）打包器。

思路（智能壳，非 fat 二进制合并）：
  - 一个 .app，双击后启动器检测当前机器架构（uname -m）；
  - Resources 下放两套 Python 运行时：python_arm64/ 与 python_x86/；
  - 引擎与数据（app/：纯 Python + 数据文件，无架构差异）只放一份，两套运行时共用。
  - 启动器按架构选对应 python 启动同一个 server.py。

为什么不做真正的 universal2 fat 二进制：
  numpy/scipy/unicorn/capstone 等底层 .so 要做成 fat 需逐一 lipo 合并，风险高、
  体积接近翻倍，收益却与「双运行时 + 智能壳」相同（用户都是「一个 app 双击即用」）。

数据来源：直接复用已构建好的两个成品
  - arm64 运行时：dist_final7/GR3胶片工具.app/.../python
  - x86  运行时：dist_x86/GR3胶片工具-2.app/.../python
  - 引擎资源：dist_final7/GR3胶片工具.app/.../app（与 x86 版完全一致）
这样避免重复跑依赖复制，最稳。

用法：
  .packenv/bin/python _pack_universal.py [--out DIR]
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO)

APP_NAME = 'GR3胶片工具'
BUNDLE_ID = 'com.duccio.gr3filmtool'
VERSION = '1.0.0-universal'

# 已构建好的两个成品（数据源）—— 用修复后的干净产物（含 urllib/request.py）
SRC_ARM = os.path.join(REPO, 'dist_arm64_v2', 'GR3胶片工具-2.app')
SRC_X86 = os.path.join(REPO, 'dist_x86_v2', 'GR3胶片工具-2.app')


def _log(msg):
    print(msg, flush=True)


def _mkdirs(p):
    os.makedirs(p, exist_ok=True)


def _mb(n):
    return f'{n / 1e6:.1f} MB'


def _copy_tree(src, dst, exclude_names=()):
    os.makedirs(dst, exist_ok=True)
    n = b = 0
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if name in exclude_names:
            continue
        if os.path.islink(s):
            continue
        if os.path.isdir(s):
            a, c = _copy_tree(s, d, exclude_names)
            n += a
            b += c
        else:
            try:
                shutil.copy2(s, d)
                n += 1
                b += os.path.getsize(d)
            except OSError:
                pass
    return n, b


def _du(path):
    total = 0
    for r, _, fs in os.walk(path):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return total


LAUNCHER = r'''#!/bin/bash
# GR3 胶片工具 —— Universal（双芯片）启动器
# 双击入口：检测当前架构 → 选对应 Python 运行时 → 起同一个本地服务
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"          # …/Contents/MacOS
RES="$(cd "$HERE/../Resources" && pwd)"        # …/Contents/Resources
SERVER="$RES/app/webtool/server.py"
DATA="$HOME/Library/Application Support/GR3FilmTool"

# ---- 日志：写不了就退化成 /dev/null ----
LOG="/dev/null"
LOG_DIR="$HOME/Library/Logs/GR3FilmTool"
if mkdir -p "$LOG_DIR" 2>/dev/null && : >>"$LOG_DIR/run.log" 2>/dev/null; then
  LOG="$LOG_DIR/run.log"
fi

# ---- 临时目录兜底 ----
if [ -n "${TMPDIR:-}" ] && [ -d "${TMPDIR}" ] && [ -w "${TMPDIR}" ]; then
  :
else
  if mkdir -p "$DATA/tmp" 2>/dev/null; then
    export TMPDIR="$DATA/tmp/"
  fi
fi

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') 启动 ====="
  echo "ARCH   : $(uname -m)"
} >>"$LOG" 2>&1

# ---- 架构检测 → 选运行时 ----
ARCH="$(uname -m)"
case "$ARCH" in
  arm64|aarch64)
    PY="$RES/python_arm64/bin/python3"
    ;;
  x86_64)
    PY="$RES/python_x86/bin/python3"
    ;;
  *)
    osascript -e 'display alert "GR3 胶片工具" message "无法识别的架构：'"$ARCH"'" as critical' 2>/dev/null
    echo "不支持的架构: $ARCH" >>"$LOG"
    exit 1
    ;;
esac

echo "runtime: $PY" >>"$LOG"
echo "server : $SERVER" >>"$LOG"

if [ ! -x "$PY" ]; then
  osascript -e 'display alert "GR3 胶片工具" message "内置运行环境缺失，应用可能已损坏。\n请重新解压完整压缩包后再试。" as critical' 2>/dev/null
  echo "缺少运行时: $PY" >>"$LOG"
  exit 1
fi

# 脱离 LaunchServices 的会话限制，正常继承用户环境
exec "$PY" "$SERVER" >>"$LOG" 2>&1
'''


def _write_icns(res):
    src = os.path.join(SRC_ARM, 'Contents', 'Resources', 'AppIcon.icns')
    dst = os.path.join(res, 'AppIcon.icns')
    if os.path.exists(src):
        shutil.copy2(src, dst)
        _log(f'      AppIcon.icns {_mb(os.path.getsize(dst))}')
        return True
    _log('      ! 未找到图标，跳过')
    return False


def _write_plist(contents_dir, has_icon):
    plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>{APP_NAME}</string>
    <key>CFBundleDisplayName</key><string>GR3 胶片滤镜工具</string>
    <key>CFBundleExecutable</key><string>{APP_NAME}</string>
    <key>CFBundleIdentifier</key><string>{BUNDLE_ID}</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleSignature</key><string>????</string>
    <key>CFBundleShortVersionString</key><string>{VERSION}</string>
    <key>CFBundleVersion</key><string>{VERSION}</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
    <key>CFBundleDevelopmentRegion</key><string>zh_CN</string>
    <key>LSMinimumSystemVersion</key><string>11.0</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.photography</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSRequiresAquaSystemAppearance</key><false/>
    <key>NSHumanReadableCopyright</key><string>GR3 Film Filter Tool</string>
    {'<key>CFBundleIconFile</key><string>AppIcon</string>' if has_icon else ''}
</dict>
</plist>
'''
    p = os.path.join(contents_dir, 'Info.plist')
    with open(p, 'w') as f:
        f.write(plist)
    return p


def _selfcheck(app_path):
    res = os.path.join(app_path, 'Contents', 'Resources')
    checks = []
    for rel in ('app/webtool/server.py', 'app/webtool/paths.py', 'app/webtool/index.html',
                'app/index.html', 'app/make_slots15.py', 'app/make_slots16.py',
                'app/work/fw/rtos.bin', 'app/work/base_gamma_std.npy',
                'app/third_party/gr-custom-tool/gr4_editor/__init__.py',
                'python_arm64/bin/python3', 'python_x86/bin/python3',
                # ★ stdlib 关键文件（历史 bug：request.py 缺失导致 import urllib.request 崩溃）
                'python_arm64/lib/python3.13/urllib/request.py',
                'python_x86/lib/python3.13/urllib/request.py'):
        p = os.path.join(res, rel)
        checks.append((rel, os.path.exists(p)))
    bad = [r for r, ok in checks if not ok]
    for r, ok in checks:
        if not ok:
            _log(f'      ✗ 缺 {r}')
    if bad:
        return False

    # 两个运行时各自的 import 冒烟
    for label, arch_py in (('arm64', 'python_arm64/bin/python3'),
                           ('x86', 'python_x86/bin/python3')):
        py = os.path.join(res, arch_py)
        code = ('import sys; import numpy,scipy.optimize,PIL,colour,tifffile,capstone,unicorn;'
                'print("OK", numpy.__version__)')
        env = dict(os.environ)
        env['PYTHONPATH'] = os.path.join(res, 'app')
        p = subprocess.run([py, '-c', code], capture_output=True, text=True,
                           timeout=180, env=env, cwd=os.path.join(res, 'app'))
        ok = (p.returncode == 0 and 'OK' in (p.stdout or ''))
        _log(f'      {label} 运行时自检: {"通过 ✓" if ok else "失败 ✗"}  '
             f'{(p.stdout or p.stderr or "").strip()[-80:]}')
        if not ok:
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='dist_universal')
    args = ap.parse_args()

    if not (os.path.isdir(SRC_ARM) and os.path.isdir(SRC_X86)):
        _log('✗ 缺少数据源成品：dist_arm64_v2 与 dist_x86_v2（请先分别跑 _pack_app.py 与 _pack_app_x86.py）')
        return 1

    out_dir = os.path.join(REPO, args.out)
    app_path = os.path.join(out_dir, f'{APP_NAME}.app')
    if os.path.exists(app_path):
        for i in range(2, 40):
            cand = os.path.join(out_dir, f'{APP_NAME}-{i}.app')
            if not os.path.exists(cand):
                app_path = cand
                break

    contents = os.path.join(app_path, 'Contents')
    macos_dir = os.path.join(contents, 'MacOS')
    res = os.path.join(contents, 'Resources')
    _mkdirs(macos_dir)
    _mkdirs(res)

    _log(f'目标: {app_path}')
    t0 = time.time()

    _log('[1/4] 复制两套运行时…')
    n, b = _copy_tree(os.path.join(SRC_ARM, 'Contents', 'Resources', 'python'),
                      os.path.join(res, 'python_arm64'))
    _log(f'      python_arm64: {n} 文件 {_mb(b)}')
    n, b = _copy_tree(os.path.join(SRC_X86, 'Contents', 'Resources', 'python'),
                      os.path.join(res, 'python_x86'))
    _log(f'      python_x86: {n} 文件 {_mb(b)}')

    _log('[2/4] 复制引擎资源（共享一份）…')
    n, b = _copy_tree(os.path.join(SRC_ARM, 'Contents', 'Resources', 'app'),
                      os.path.join(res, 'app'), exclude_names=('__pycache__',))
    _log(f'      app: {n} 文件 {_mb(b)}')

    _log('[3/4] 图标…')
    has_icon = _write_icns(res)

    _log('[4/4] 启动器 + Info.plist…')
    lp = os.path.join(macos_dir, APP_NAME)
    with open(lp, 'w') as f:
        f.write(LAUNCHER)
    os.chmod(lp, 0o755)
    _write_plist(contents, has_icon)

    total = _du(app_path)
    _log('')
    ok = _selfcheck(app_path)
    _log('')
    _log(f'总体积: {_mb(total)}    耗时: {time.time() - t0:.1f}s')
    _log('自检: ' + ('通过 ✓' if ok else '未通过 ✗'))
    _log('产物: ' + app_path)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
