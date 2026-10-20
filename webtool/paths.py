#!/usr/bin/env python3
"""统一路径解析 —— 区分「只读资源」与「用户可写数据」两层。

为什么需要它：
  macOS .app 的内部（Contents/Frameworks，或 PyInstaller 的 _internal）是只读的，
  而本工具要写三种东西：胶片库、解锁状态、生成的固件。
  所以资源与用户数据必须分开存放。

  RESOURCE_DIR  只读：引擎 .py、work/ 拟合数据、third_party 编解码器、index.html、固件
  USER_DIR      可写：胶片库、license、新建胶片的拟合产物、生成的固件
                （macOS: ~/Library/Application Support/GR3FilmTool）

开发环境（未打包）下 USER_DIR 也用同一个位置，这样「开发时跑出来的东西」和
「打包后的 app 跑出来的东西」是同一份，便于对比排查。
"""
import hashlib
import os
import shutil
import sys

APP_NAME = 'GR3FilmTool'

# GR III 2.10 官方固件 fwdc239b.bin 的 SHA256（与 build_firmware.py 一致）
OFFICIAL_FW_SHA = 'd6a3c9c288d784080e7b283222ecdd8752adfeed6faa36dab44f73115354bfd4'


def _resource_dir():
    """只读资源根：打包环境 = _internal；开发环境 = 仓库根。"""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        # macOS .app：可执行文件在 Contents/MacOS/，资源在 Contents/Frameworks/
        for cand in (os.path.join(exe_dir, '..', 'Frameworks'),
                     os.path.join(exe_dir, '_internal'),
                     getattr(sys, '_MEIPASS', '') or exe_dir,
                     exe_dir):
            cand = os.path.abspath(cand)
            if os.path.exists(os.path.join(cand, 'make_slots15.py')):
                return cand
        return os.path.abspath(os.path.join(exe_dir, '_internal'))
    # 开发环境：本文件在 webtool/ 下，上一层是仓库根
    here = os.path.dirname(os.path.abspath(__file__))
    for up in range(0, 4):
        cand = os.path.abspath(os.path.join(here, *(['..'] * up)))
        if os.path.exists(os.path.join(cand, 'make_slots15.py')):
            return cand
    return os.path.abspath(os.path.join(here, '..'))


def _user_dir():
    """用户可写根目录（各平台标准位置）。可用 GR3_USER_DIR 覆盖（便于测试）。"""
    if os.environ.get('GR3_USER_DIR'):
        return os.path.abspath(os.environ['GR3_USER_DIR'])
    if sys.platform == 'darwin':
        base = os.path.expanduser('~/Library/Application Support')
    elif sys.platform.startswith('win'):
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
    else:
        base = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
    return os.path.join(base, APP_NAME)


RESOURCE_DIR = _resource_dir()
USER_DIR = _user_dir()

# —— 用户可写子路径 ——
LIB_PATH = os.path.join(USER_DIR, 'film_library.json')
LICENSE_PATH = os.path.join(USER_DIR, 'license.json')
OUTPUT_DIR = os.path.join(USER_DIR, 'output')
WORK_DIR = os.path.join(USER_DIR, 'work')                    # 新建胶片的拟合中间产物
CUBE_DIR = os.path.join(WORK_DIR, 'cubes')
FITS_DIR = os.path.join(WORK_DIR, 'fits')
USER_FW_DIR = os.path.join(USER_DIR, 'official_firmware')

# —— 只读资源子路径 ——
RES_FITS_V16 = os.path.join(RESOURCE_DIR, 'work', 'films_v16', 'fits', 'duccio')
RES_MA_PROBE = os.path.join(RESOURCE_DIR, 'work', 'ma_probe5')
RES_INDEX_HTML = os.path.join(RESOURCE_DIR, 'index.html')


def ensure_user_dirs():
    """建好可写目录；首次运行时把只读的胶片库「播种」到用户目录。"""
    for d in (USER_DIR, OUTPUT_DIR, WORK_DIR, CUBE_DIR, FITS_DIR, USER_FW_DIR):
        os.makedirs(d, exist_ok=True)
    # 胶片库：用户目录没有就从资源目录拷一份作为初始状态
    if not os.path.exists(LIB_PATH):
        seed = os.path.join(RESOURCE_DIR, 'film_library.json')
        if os.path.exists(seed):
            try:
                shutil.copy2(seed, LIB_PATH)
            except Exception:
                pass
        if not os.path.exists(LIB_PATH):
            with open(LIB_PATH, 'w', encoding='utf-8') as f:
                f.write('{"films": {}}')
    return USER_DIR


def _fw_sha_ok(p):
    """固件是否为 GR III 2.10 官方原件（按 SHA256 判定）。

    只按文件名找固件是不够的：用户目录里可能存着「已被改过」的同名副本
    （例如自己上次生成的结果被命名为 fwdc239b.bin），一选它就会报
    「固件不匹配」，而用户会误以为是自己下的固件坏了。
    """
    try:
        if not os.path.isfile(p) or os.path.getsize(p) < 1024 * 1024:
            return False
        h = hashlib.sha256()
        with open(p, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        return h.hexdigest() == OFFICIAL_FW_SHA
    except Exception:
        return False


def find_firmware():
    """定位官方固件 fwdc239b.bin（GR III 2.10）。

    只读资源里不随包分发官方固件（理光不允许转发），所以按用户常见位置逐个找：
      1. 环境变量 GR3_FW 显式指定
      2. 用户数据目录 official_firmware/
      3. app 资源目录 official_firmware/
      4. 桌面 / 下载 目录（含其下一级子目录，覆盖「GR3魔改固件/官方固件」这类归档习惯）

    两趟扫描：先找 SHA256 正确的官方原件；全都不是时才退回「按文件名命中」的
    候选（调用方会给出「固件不匹配」的明确报错，比静默失败好）。
    返回路径字符串；找不到时返回约定路径，供调用方判断并给出清晰提示。
    """
    if os.environ.get('GR3_FW'):
        return os.path.abspath(os.environ['GR3_FW'])

    names = ('fwdc239b.bin', 'fwdc239b_GR3_2.10_official.bin', 'fwdc239b_GR3_2.10.bin')

    # 收集候选（保持调用方设定的优先级顺序）
    cands = []
    for d in (USER_FW_DIR, os.path.join(RESOURCE_DIR, 'official_firmware')):
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                cands.append(p)
        if os.path.isdir(d):
            try:
                for fn in sorted(os.listdir(d)):
                    if (fn.lower().endswith('.bin') and 'GR4' not in fn.upper()
                            and '248' not in fn):
                        cands.append(os.path.join(d, fn))
            except Exception:
                pass

    home = os.path.expanduser('~')
    for root in (os.path.join(home, 'Desktop'), os.path.join(home, 'Downloads')):
        if not os.path.isdir(root):
            continue
        for n in names:
            p = os.path.join(root, n)
            if os.path.exists(p):
                cands.append(p)
        # 一级 / 二级子目录（如 Desktop/GR3魔改固件/官方固件/fwdc239b.bin）
        try:
            for sub in sorted(os.listdir(root)):
                subp = os.path.join(root, sub)
                if not os.path.isdir(subp) or sub.startswith('.'):
                    continue
                for n in names:
                    p = os.path.join(subp, n)
                    if os.path.exists(p):
                        cands.append(p)
                for sub2 in sorted(os.listdir(subp))[:40]:
                    sub2p = os.path.join(subp, sub2)
                    if not os.path.isdir(sub2p):
                        continue
                    for n in names:
                        p = os.path.join(sub2p, n)
                        if os.path.exists(p):
                            cands.append(p)
        except Exception:
            pass

    # 去重（保序）
    seen = set()
    uniq = []
    for p in cands:
        if p not in seen:
            seen.add(p)
            uniq.append(p)

    # 第一趟：SHA 正确的官方原件优先
    for p in uniq:
        if _fw_sha_ok(p):
            return p
    # 第二趟：退化为首个文件名命中者（调用方会报「固件不匹配」）
    if uniq:
        return uniq[0]

    # 未找到：返回约定位置，调用方据此提示用户放哪里
    return os.path.join(USER_FW_DIR, 'fwdc239b.bin')
