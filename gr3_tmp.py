"""不依赖 tempfile 的临时目录 / 临时文件工厂。

为什么要自己实现
----------------
CPython 的 `tempfile` 模块在初始化时会**逐个尝试候选目录**，判断手段是
「在其中建一个测试文件、再把它删掉」。只要删除被拦住（沙箱、部分企业
MDM 管控、只读挂载的 /tmp 等），所有候选都会判定为不可用，整个模块随之
失效并抛出：

    FileNotFoundError: [Errno 2] No usable temporary directory found in [...]

此时 `TemporaryDirectory()` / `NamedTemporaryFile()` 全部不可用，引擎里
凡是需要「搭个临时工作目录」的步骤（如 armasm 调 clang 汇编）都会直接崩。

本模块改为在**已知可写的用户数据目录**下建固定 scratch 区，用
`os.makedirs` 创建、退出时 `shutil.rmtree(..., ignore_errors=True)`
尽力清理 —— 清不掉也不影响功能正确性，只是留些垃圾文件。

对外接口（替代对应物）
--------------------
    temp_dir(prefix)      <-> tempfile.TemporaryDirectory(prefix=...)
    temp_path(suffix)     <-> 生成唯一路径（不落盘，调用方自己写）
    write_bytes(data, suffix) <-> NamedTemporaryFile(delete=False) + write
    cleanup(path)         <-> os.unlink，失败静默

查找顺序：GR3_SCRATCH_DIR 环境变量 → 用户数据目录(tmp/) → $TMPDIR/gr3
→ ~/.gr3-scratch → 当前目录/.gr3-scratch。第一个能建得出来的胜出。
"""
import contextlib
import itertools
import os
import shutil
import sys

_counter = itertools.count()


def _user_dir():
    """拿 paths.USER_DIR（优先同目录，其次 webtool/ 子目录）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.path.join(here, 'webtool')):
        if os.path.exists(os.path.join(base, 'paths.py')) and base not in sys.path:
            sys.path.insert(0, base)
            break
    try:
        import paths
        return getattr(paths, 'USER_DIR', None)
    except Exception:
        return None


def _candidates():
    c = []
    if os.environ.get('GR3_SCRATCH_DIR'):
        c.append(os.environ['GR3_SCRATCH_DIR'])
    ud = _user_dir()
    if ud:
        c.append(os.path.join(ud, 'tmp'))
    if os.environ.get('TMPDIR'):
        c.append(os.path.join(os.environ['TMPDIR'], 'gr3'))
    c.append(os.path.join(os.path.expanduser('~'), '.gr3-scratch'))
    c.append(os.path.join(os.getcwd(), '.gr3-scratch'))
    return c


def root():
    """返回第一个建得出来的 scratch 根目录（缓存）。"""
    global _ROOT
    if _ROOT:
        return _ROOT
    last = None
    for c in _candidates():
        try:
            os.makedirs(c, exist_ok=True)
            _ROOT = c
            return c
        except Exception as e:      # 权限不足 / 路径非法，换下一个
            last = e
            continue
    raise RuntimeError(f'找不到可写的临时目录（最后一个错误：{last}）')


_ROOT = None


def _unique(prefix):
    # pid + 单调计数器，保证同一进程内不重名，跨进程也不撞
    return f'{prefix}{os.getpid()}-{next(_counter)}'


@contextlib.contextmanager
def temp_dir(prefix='gr3-'):
    """等价于 tempfile.TemporaryDirectory：退出时尽力删除。"""
    d = os.path.join(root(), _unique(prefix))
    os.makedirs(d, exist_ok=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)   # 删不掉就算了，不能因此报错


def temp_path(suffix='', prefix='gr3-'):
    """返回一个唯一路径（不创建文件）。调用方负责写入与清理。"""
    return os.path.join(root(), _unique(prefix) + suffix)


def write_bytes(data, suffix='', prefix='gr3-'):
    """把 bytes 落盘到唯一路径，返回该路径。"""
    p = temp_path(suffix, prefix)
    with open(p, 'wb') as f:
        f.write(data)
    return p


def write_text(text, suffix='', prefix='gr3-', encoding='utf-8'):
    p = temp_path(suffix, prefix)
    with open(p, 'w', encoding=encoding) as f:
        f.write(text)
    return p


def cleanup(path):
    """删除单个文件，失败静默（受限环境下删除会被拦）。"""
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def patch_tempfile():
    """给 stdlib tempfile 兜底：预先指定 tempdir，跳过它的「建了再删」探测。

    tempfile.gettempdir() 的实现是 `if tempdir is None: tempdir = _get_default_tempdir()`，
    只要预先赋值就完全绕开探测。这样即使删除受限，第三方库（Pillow、PyInstaller
    运行时等）用的 tempfile 也能正常工作。返回生效的目录，失败返回 None。
    """
    try:
        import tempfile as _tf
        if _tf.tempdir:
            return _tf.tempdir
        _tf.tempdir = root()
        return _tf.tempdir
    except Exception:
        return None
