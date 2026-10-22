"""Assemble a small ARM (A32) stub at a fixed address with the system clang (LLVM-based cross-assembler).

One instruction per line, optional 'label:' prefix, '@' comments. Branches to absolute firmware addresses are
written 'bl abs(0xADDR)' / 'b abs(0xADDR)' (also beq/bne/blo/bhs) and encoded here; local labels are resolved by the
assembler. `.word` lines are allowed. Returns a list of 32-bit words (little-endian in the image).

No Homebrew LLVM needed: uses /usr/bin/clang --target=armv7a-none-eabi to assemble, then parses the ELF .o to
extract the .text machine code (replacing llvm-objcopy).

临时目录用 gr3_tmp 而非 stdlib tempfile：在「禁止删除文件」的受限环境（沙箱、
部分 MDM 管控机）下 tempfile 模块会整体失效，这里改为在用户数据目录下自建
scratch 区，保证打包后的 app 也能正常汇编。
"""
import os, re, sys, shutil, subprocess, struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gr3_tmp  # noqa: E402

COND = {'b': 0xE, 'beq': 0x0, 'bne': 0x1, 'blo': 0x3, 'bhs': 0x2, 'bls': 0x9, 'bhi': 0x8}

# clang 查找顺序：环境变量 CLANG → PATH → 常见安装位置。
# Windows 默认没有 /usr/bin/clang，也不在 PATH 里（此前报 FileNotFoundError [WinError 2]），
# 所以必须显式扫描常见安装目录，找不到时给出可执行的安装指引。


def _env_clang():
    v = os.environ.get('CLANG', '').strip()
    if not v:
        return None
    if os.path.isfile(v) or shutil.which(v):
        return v
    raise RuntimeError(
        f'环境变量 CLANG 指向的文件不存在：{v}\n'
        f'The CLANG environment variable points to a non-existent file.'
    )


def _path_clang():
    return shutil.which('clang') or shutil.which('clang.exe')


def _common_clang():
    cands = []
    if sys.platform == 'win32':
        pf = os.environ.get('ProgramFiles', r'C:\Program Files')
        pf86 = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
        lad = os.environ.get('LocalAppData', os.path.expanduser(r'~\AppData\Local'))
        cands += [
            rf'{pf}\LLVM\bin\clang.exe',
            rf'{pf86}\LLVM\bin\clang.exe',
            rf'{lad}\LLVM\bin\clang.exe',
            r'C:\LLVM\bin\clang.exe',
        ]
    else:
        cands += [
            '/usr/bin/clang',
            '/opt/homebrew/opt/llvm/bin/clang',
            '/usr/local/opt/llvm/bin/clang',
            '/usr/local/bin/clang',
        ]
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def find_clang():
    return _env_clang() or _path_clang() or _common_clang()


_CLANG_MISS = (
    '未找到 clang（LLVM 编译器），汇编 ARM 指令需要它。\n'
    'clang (LLVM) not found — it is required to assemble the ARM stub.\n'
    '解决办法 / How to fix:\n'
    '  Windows: 安装 LLVM，任选其一 ——\n'
    '    1) winget install LLVM.LLVM   （装完重开终端）\n'
    '    2) 到 https://github.com/llvm/llvm-project/releases 下载\n'
    '       clang+llvm-…-x86_64-pc-windows-msvc 安装包，安装时勾选\n'
    '       "Add LLVM to system PATH"\n'
    '    3) 已装但不想加 PATH：set CLANG=C:\\Program Files\\LLVM\\bin\\clang.exe\n'
    '  macOS: xcode-select --install （或 brew install llvm）\n'
    '  Linux: sudo apt install clang'
)


def _elf_text(obj_bytes):
    """Extract the .text section bytes from a 32-bit ELF object file (little-endian)."""
    assert obj_bytes[:4] == b'\x7fELF', 'not an ELF file'
    e_shoff = struct.unpack('<I', obj_bytes[32:36])[0]
    e_shentsize = struct.unpack('<H', obj_bytes[46:48])[0]
    e_shnum = struct.unpack('<H', obj_bytes[48:50])[0]
    e_shstrndx = struct.unpack('<H', obj_bytes[50:52])[0]

    def section(i):
        off = e_shoff + i * e_shentsize
        return struct.unpack('<IIIIII', obj_bytes[off:off + 24])

    _, _, _, _, str_off, str_size = section(e_shstrndx)
    strtab = obj_bytes[str_off:str_off + str_size]

    def sname(sh_name):
        end = strtab.find(b'\x00', sh_name)
        return strtab[sh_name:end].decode()

    for i in range(e_shnum):
        n, _, _, _, off, sz = section(i)
        if sname(n) == '.text':
            return obj_bytes[off:off + sz]
    raise RuntimeError('.text section not found in ELF object')


def assemble(src, base):
    lines = [l.split('@')[0].rstrip() for l in src.strip().splitlines()]
    lines = [l for l in lines if l.strip()]
    fixed = []
    for i, l in enumerate(lines):
        at = base + 4 * i
        m = re.match(r'^\s*(\w+:\s*)?(bl|b|beq|bne|blo|bhs|bls|bhi)\s+abs\((0x[0-9a-fA-F]+)\)\s*$', l)
        if m:
            off = ((int(m.group(3), 16) - at - 8) >> 2) & 0xFFFFFF
            word = 0xEB000000 | off if m.group(2) == 'bl' else (COND[m.group(2)] << 28) | 0x0A000000 | off
            fixed.append(f'{m.group(1) or ""}.word {word:#x}')
        else:
            fixed.append(l)
    # 首选内置纯 Python 汇编器（零外部依赖，与 clang 逐字节一致——已对全部真实
    # 调用点做差分验证）。超出内置子集的形态回退到 clang（若有）。
    try:
        import armmini
        return armmini.assemble_lines(fixed, base)
    except ImportError:
        pass
    except armmini.Unsupported:
        pass  # 落到 clang 路径
    with gr3_tmp.temp_dir('asm-') as d:
        s, o = (os.path.join(d, n) for n in ('a.s', 'a.o'))
        with open(s, 'w') as f:
            f.write('.syntax unified\n.arm\n.text\n' + '\n'.join(fixed) + '\n')
        clang = find_clang()
        if not clang:
            raise RuntimeError(_CLANG_MISS)
        try:
            r = subprocess.run([clang, '--target=armv7a-none-eabi', '-c', '-o', o, s],
                               capture_output=True, text=True)
        except FileNotFoundError:
            raise RuntimeError(_CLANG_MISS)
        if r.returncode:
            raise RuntimeError(r.stderr)
        with open(o, 'rb') as f:
            data = _elf_text(f.read())
    assert len(data) == 4 * len(lines), (len(data), len(lines))
    return [int.from_bytes(data[i:i + 4], 'little') for i in range(0, len(data), 4)]
