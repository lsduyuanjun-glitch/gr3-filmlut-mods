"""Assemble a small ARM (A32) stub at a fixed address with the system clang (LLVM-based cross-assembler).

One instruction per line, optional 'label:' prefix, '@' comments. Branches to absolute firmware addresses are
written 'bl abs(0xADDR)' / 'b abs(0xADDR)' (also beq/bne/blo/bhs) and encoded here; local labels are resolved by the
assembler. `.word` lines are allowed. Returns a list of 32-bit words (little-endian in the image).

No Homebrew LLVM needed: uses /usr/bin/clang --target=armv7a-none-eabi to assemble, then parses the ELF .o to
extract the .text machine code (replacing llvm-objcopy).
"""
import os, re, subprocess, tempfile, struct

CLANG = os.environ.get('CLANG', '/usr/bin/clang')
COND = {'b': 0xE, 'beq': 0x0, 'bne': 0x1, 'blo': 0x3, 'bhs': 0x2, 'bls': 0x9, 'bhi': 0x8}


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
    with tempfile.TemporaryDirectory() as d:
        s, o = (os.path.join(d, n) for n in ('a.s', 'a.o'))
        open(s, 'w').write('.syntax unified\n.arm\n.text\n' + '\n'.join(fixed) + '\n')
        r = subprocess.run([CLANG, '--target=armv7a-none-eabi', '-c', '-o', o, s],
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr)
        data = _elf_text(open(o, 'rb').read())
    assert len(data) == 4 * len(lines), (len(data), len(lines))
    return [int.from_bytes(data[i:i + 4], 'little') for i in range(0, len(data), 4)]
