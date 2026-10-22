"""纯 Python 的 ARMv7-A (A32) 迷你汇编器 —— 只覆盖本项目引擎模板实际用到的指令子集。

背景：此前 armasm.py 依赖外部 clang（--target=armv7a-none-eabi）汇编 ARM 存根，
Windows 用户必须先安装 LLVM 才能生成固件。这里内置一个精确子集的汇编器，
生成的机器码与 clang 逐字节一致（已用真实构建的全部调用点做差分验证），
从而三大平台都不再需要任何外部编译器。

设计原则（安全第一）：
- 只接受精确匹配的指令形态；任何没见过的写法抛 Unsupported，
  由 armasm.py 回退到 clang 路径（行为与旧版完全一致），绝不猜测编码。
- 条件码、寄存器（含 ip/lr/pc/sp）、桶形移位（lsl/lsr/asr/ror #imm）、
  ARM 修改立即数（rotate right 编码）都严格按 ARMv7-A 手册实现。

支持的指令（对照真实构建中出现的全部形态）：
  数据处理:  mov/mvn/and/eor/sub/rsb/add/adc/sbc/tst/teq/cmp/cmn/orr/bic
             （含 {s} 变体如 subs/orrs；含条件码变体如 movhs/addlo/subne/cmpeq/cmphs）
             操作数: Rd, #imm | Rd, Rm | Rd, Rn, op2；op2 = Rm / #imm / Rm{, lsl|lsr|asr|ror #imm}
  专用:      movw/movt Rd, #imm16 · bx{cond} Rm · mul · mla · bfi Rd, Rn, #lsb, #width
  访存:      ldr/str/ldrb/strb/ldrh/strh/ldrsb/ldrsh
             [Rn] · [Rn, #±imm] · [Rn, Rm] · [Rn, Rm, lsl #imm] · [Rn], #imm（后索引用于 strh）
  块访存:    ldm/stm Rn, {寄存器列表}（IA 不回写）· push {…} · pop {…}（支持 r4-r7 区间）
  其他:      b/bl/beq/bne/blo/bhs/bls/bhi 到本地标号（两遍扫描）· .word imm · nop
"""

import re


class Unsupported(Exception):
    """当前指令超出内置子集，调用方应回退到 clang。"""


# ————————————————————————————————————————————————
# 寄存器与条件码
# ————————————————————————————————————————————————
_REGS = {}
for _i in range(16):
    _REGS['r%d' % _i] = _i
_REGS.update({'ip': 12, 'sp': 13, 'lr': 14, 'pc': 15})

_CONDS = {'eq': 0, 'ne': 1, 'cs': 2, 'hs': 2, 'cc': 3, 'lo': 3, 'mi': 4, 'pl': 5,
          'vs': 6, 'vc': 7, 'hi': 8, 'ls': 9, 'ge': 10, 'lt': 11, 'gt': 12, 'le': 13,
          'al': 14}

_SHIFT_TYPES = {'lsl': 0, 'lsr': 1, 'asr': 2, 'ror': 3}


def _reg(tok):
    r = _REGS.get(tok.strip().lower())
    if r is None:
        raise Unsupported('not a register: %r' % tok)
    return r


def _cond(mn):
    """拆出助记符里的条件码后缀，返回 (基础助记符, cond编码)。"""
    if len(mn) > 2 and mn[-2:] in _CONDS:
        return mn[:-2], _CONDS[mn[-2:]]
    if len(mn) == 3 and mn[-2:] in _CONDS:  # 3 字母助记符整体可能是条件形式
        pass
    return mn, 14  # al


def _ror32(v, n):
    n &= 31
    return ((v >> n) | (v << (32 - n))) & 0xFFFFFFFF


def _imm12(value):
    """ARM 数据处理「修改立即数」编码：操作数 = imm8 ROR (2*rot)。
    即 imm8 = value 循环左移 2*rot（= 右移 32-2*rot）。返回 12 位编码，失败抛 Unsupported。"""
    if value < 0:
        raise Unsupported('negative immediate %d' % value)
    if value > 0xFFFFFFFF:
        raise Unsupported('immediate overflow %d' % value)
    if value <= 0xFF:
        return value
    for rot in range(1, 16):
        v = _ror32(value, (32 - 2 * rot) % 32)
        if v <= 0xFF:
            return (rot << 8) | v
    raise Unsupported('immediate %#x not encodable as ARM modified immediate' % value)


# ————————————————————————————————————————————————
# 操作数解析
# ————————————————————————————————————————————————
_FLEX_IMM = re.compile(r'^#(0x[0-9a-fA-F]+|\d+)$')
_SHIFT = re.compile(r'^(lsl|lsr|asr|ror)\s*#(0x[0-9a-fA-F]+|\d+)$')


def _flex_operand(text):
    """解析 DP 的 op2，返回 (I, operand12)。I=1 表示立即数。"""
    text = text.strip()
    m = _FLEX_IMM.match(text)
    if m:
        v = int(m.group(1), 0)
        return 1, _imm12(v)
    # 寄存器 + 可选移位：I=0（I 位只用于立即数），op12 = sh<<7 | type<<5 | Rm
    parts = text.split(',', 1)
    rm = _reg(parts[0])
    if len(parts) == 1:
        return 0, rm
    m = _SHIFT.match(parts[1].strip())
    if not m:
        raise Unsupported('unsupported operand shift: %r' % text)
    typ = _SHIFT_TYPES[m.group(1)]
    sh = int(m.group(2), 0)
    if not (0 <= sh <= 31):
        raise Unsupported('shift amount %d' % sh)
    return 0, (sh << 7) | (typ << 5) | rm


def _dp(mn_base, cond, s, rest):
    """数据处理类。返回 32 位机器码。"""
    table = {'and': 0, 'eor': 1, 'sub': 2, 'rsb': 3, 'add': 4, 'adc': 5, 'sbc': 6,
             'rsc': 7, 'tst': 8, 'teq': 9, 'cmp': 10, 'cmn': 11, 'orr': 12,
             'mov': 13, 'bic': 14, 'mvn': 15}
    if mn_base not in table:
        raise Unsupported('dp mnemonic %r' % mn_base)
    opcode = table[mn_base]
    # 读写类（Rd 是目的）；比较/测试类 Rd=0 且不需要目的
    sets_flags = mn_base in ('tst', 'teq', 'cmp', 'cmn') or s
    if mn_base in ('tst', 'teq', 'cmp', 'cmn'):
        args = [a.strip() for a in rest.split(',')]
        if len(args) not in (2,):
            raise Unsupported('%s operand count' % mn_base)
        rn = _reg(args[0])
        I, op2 = _flex_operand(args[1])
        return ((cond << 28) | (1 << 25 if I else 0) | (1 << 20) | (opcode << 21)
                | (rn << 16) | op2)
    args = [a.strip() for a in rest.split(',')]
    rd = _reg(args[0])
    if len(args) == 2:
        # mov/mvn Rd, op2（Rn=0）
        if mn_base not in ('mov', 'mvn'):
            raise Unsupported('%s with 2 operands' % mn_base)
        I, op2 = _flex_operand(args[1])
        return ((cond << 28) | (1 << 25 if I else 0) | (opcode << 21) | (s << 20)
                | (rd << 12) | op2)
    if len(args) == 3 or len(args) == 4:
        rn = _reg(args[1])
        # 第 3/4 个逗号段合起来是 op2（如 'ip, lsl #3'）
        op2_text = ', '.join(args[2:])
        I, op2 = _flex_operand(op2_text)
        return ((cond << 28) | (1 << 25 if I else 0) | (opcode << 21) | (s << 20)
                | (rn << 16) | (rd << 12) | op2)
    raise Unsupported('%s operand forms' % mn_base)


# ————————————————————————————————————————————————
# 访存
# ————————————————————————————————————————————————
_MEM = re.compile(
    r'^\[\s*(r\d+|ip|sp|lr|pc)\s*(?:,\s*(.+?)\s*)?\](\s*,\s*(#-?(?:0x[0-9a-fA-F]+|\d+)))?$')
_REGOFF_SHIFT = re.compile(r'^(r\d+|ip|sp|lr|pc)\s*,\s*(lsl|lsr|asr|ror)\s*#(0x[0-9a-fA-F]+|\d+)$')


def _mem_access(mn, cond, rest):
    """ldr/str 系列。word/byte 走一条编码，halfword/sign-extend 走另一条。"""
    table = {'ldr': ('w', 1), 'str': ('w', 0), 'ldrb': ('b', 1), 'strb': ('b', 0),
             'ldrh': ('h', 1), 'strh': ('h', 0), 'ldrsb': ('sb', 1), 'ldrsh': ('sh', 1)}
    if mn not in table:
        raise Unsupported('mem mnemonic %r' % mn)
    kind, load = table[mn]
    args = [a.strip() for a in rest.split(',', 1)]
    if len(args) != 2:
        raise Unsupported('%s operand count' % mn)
    rt = _reg(args[0])
    m = _MEM.match(args[1])
    if not m:
        raise Unsupported('addressing form %r' % args[1])
    rn = _reg(m.group(1))
    inner = (m.group(2) or '').strip()
    post = m.group(4)  # [Rn], #imm 形式

    if post is not None:
        if inner:
            raise Unsupported('post-index with inner offset %r' % args[1])
        txt = post.strip().lstrip('#')
        neg = txt.startswith('-')
        p, u, w = 0, 0 if neg else 1, 0
        imm = int(txt.lstrip('-'), 0)
        reg_off = None
        shift = None
    elif not inner:
        p, u, w, imm, reg_off, shift = 1, 1, 0, 0, None, None
    elif inner.startswith('#'):
        txt = inner.lstrip('#')
        neg = txt.startswith('-')
        imm = int(txt.lstrip('-'), 0)
        p, u, w = 1, 0 if neg else 1, 0
        reg_off = None
        shift = None
    else:
        # 寄存器偏移（可带移位）
        p, u, w = 1, 1, 0
        imm = None
        sm = _REGOFF_SHIFT.match(inner)
        if sm:
            reg_off = _reg(sm.group(1))
            shift = (_SHIFT_TYPES[sm.group(2)] << 5) | (int(sm.group(3), 0) << 7)
        else:
            reg_off = _reg(inner)
            shift = None

    if kind == 'w' or kind == 'b':
        b = 1 if kind == 'b' else 0
        word = ((cond << 28) | (1 << 26) | (p << 24) | (u << 23) | (b << 22)
                | (w << 21) | (load << 20) | (rn << 16) | (rt << 12))
        if reg_off is None:
            if imm is None:
                raise Unsupported('mem offset')
            if imm < 0 or imm > 0xFFF:
                raise Unsupported('mem imm %#x' % imm)
            return word | imm
        I = 1
        op12 = (shift or 0) | reg_off
        return word | (1 << 25) | op12
    # halfword / sign-extend: cond 000 P U W L Rn Rt [11:8]=imm4H [7:4]=op [3:0]=imm4L/Rm
    # 立即数偏移 bit22=1；寄存器偏移 bit22=0、Rm 在 [3:0]
    sel = {'h': 0b1011, 'sb': 0b1101, 'sh': 0b1111}[kind]
    word = ((cond << 28) | (p << 24) | (u << 23) | (w << 21) | (load << 20)
            | (rn << 16) | (rt << 12) | (sel << 4))
    if reg_off is None:
        if imm is None:
            raise Unsupported('mem offset')
        if imm < 0 or imm > 0xFF:
            raise Unsupported('halfword imm %d' % imm)
        return word | (1 << 22) | ((imm & 0xF0) << 4) | (imm & 0xF)
    return word | reg_off


# ————————————————————————————————————————————————
# 块访存与栈
# ————————————————————————————————————————————————
def _reglist(text):
    """'{r4-r7, lr}' → 16 位掩码。"""
    t = text.strip()
    if not (t.startswith('{') and t.endswith('}')):
        raise Unsupported('reglist %r' % t)
    mask = 0
    for part in t[1:-1].split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            lo, hi = _reg(a), _reg(b)
            if lo > hi:
                raise Unsupported('reglist range %r' % part)
            for r in range(lo, hi + 1):
                mask |= 1 << r
        else:
            mask |= 1 << _reg(part)
    return mask


def _block(mn, cond, rest):
    if mn in ('push', 'pop'):
        mask = _reglist(rest)
        if mn == 'push':
            return (cond << 28) | 0x92D0000 | mask   # stmdb sp!
        return (cond << 28) | 0x8BD0000 | mask       # ldmia sp!
    args = [a.strip() for a in rest.split(',', 1)]
    if len(args) != 2:
        raise Unsupported('%s operand count' % mn)
    rn = _reg(args[0])
    mask = _reglist(args[1])
    if mn == 'ldm':
        return (cond << 28) | 0x8900000 | (rn << 16) | mask
    if mn == 'stm':
        return (cond << 28) | 0x8800000 | (rn << 16) | mask
    raise Unsupported('block mnemonic %r' % mn)


# ————————————————————————————————————————————————
# 主汇编器（两遍：第一遍算标号地址，第二遍编码）
# ————————————————————————————————————————————————
_WORD = re.compile(r'^\.word\s+(0x[0-9a-fA-F]+|\d+)$', re.I)
_LABEL = re.compile(r'^(\w+):\s*(.*)$')


def _parse_one(line, at, labels):
    """汇编一行（label 已剥离），返回机器码。标号引用在 labels 里查。"""
    mn_all = line.split()[0]
    mn, cond = _cond(mn_all)
    rest = line[len(mn_all):].strip()

    if mn == '.word':
        m = _WORD.match(line)
        if not m:
            raise Unsupported('.word form %r' % line)
        return int(m.group(1), 0) & 0xFFFFFFFF
    if mn == 'nop':
        return 0xE320F000
    if mn in ('b', 'bl'):
        if rest.startswith('abs('):
            raise Unsupported('abs branch handled by caller')
        if rest not in labels:
            raise Unsupported('undefined label %r' % rest)
        off = (labels[rest] - at - 8) >> 2
        if not (-(1 << 24) <= off < (1 << 24)):
            raise Unsupported('branch out of range')
        return (cond << 28) | (0xB << 24 if mn == 'bl' else 0xA << 24) | (off & 0xFFFFFF)
    if mn in ('bx',):
        args = rest.split(',')
        if len(args) != 1:
            raise Unsupported('bx form')
        return (cond << 28) | 0x12FFF10 | _reg(args[0])
    if mn in ('movw', 'movt'):
        m = re.match(r'^(r\d+|ip|sp|lr|pc)\s*,\s*#(0x[0-9a-fA-F]+|\d+)$', rest)
        if not m:
            raise Unsupported('%s form %r' % (mn, rest))
        v = int(m.group(2), 0)
        if not (0 <= v <= 0xFFFF):
            raise Unsupported('%s imm16 %d' % (mn, v))
        rd = _reg(m.group(1))
        base = 0x3000000 if mn == 'movw' else 0x3400000
        return (cond << 28) | base | ((v >> 12) << 16) | (rd << 12) | (v & 0xFFF)
    if mn == 'mul':
        args = [a.strip() for a in rest.split(',')]
        if len(args) != 3:
            raise Unsupported('mul operands')
        rd, rm, rs = _reg(args[0]), _reg(args[1]), _reg(args[2])
        return (cond << 28) | (rd << 16) | (rs << 8) | 0x90 | rm
    if mn == 'mla':
        args = [a.strip() for a in rest.split(',')]
        if len(args) != 4:
            raise Unsupported('mla operands')
        rd, rm, rs, ra = (_reg(a) for a in args)
        return (cond << 28) | (1 << 21) | (rd << 16) | (ra << 12) | (rs << 8) | 0x90 | rm
    if mn == 'bfi':
        m = re.match(r'^(r\d+|ip|sp|lr|pc)\s*,\s*(r\d+|ip|sp|lr|pc)\s*,\s*#(\d+)\s*,\s*#(\d+)$', rest)
        if not m:
            raise Unsupported('bfi form %r' % rest)
        rd, rn, lsb, width = _reg(m.group(1)), _reg(m.group(2)), int(m.group(3)), int(m.group(4))
        msb = lsb + width - 1
        if not (0 <= lsb <= 31 and 1 <= width <= 32 and msb <= 31):
            raise Unsupported('bfi lsb/width')
        return (cond << 28) | 0x7C00010 | (msb << 16) | (rd << 12) | (lsb << 7) | rn
    if mn in ('ldr', 'str', 'ldrb', 'strb', 'ldrh', 'strh', 'ldrsb', 'ldrsh'):
        return _mem_access(mn, cond, rest)
    if mn in ('ldm', 'stm', 'push', 'pop'):
        return _block(mn, cond, rest)
    if mn in ('and', 'eor', 'sub', 'rsb', 'add', 'adc', 'sbc', 'rsc',
              'tst', 'teq', 'cmp', 'cmn', 'orr', 'mov', 'bic', 'mvn'):
        return _dp(mn, cond, 0, rest)
    # {s} 变体：orrs / subs / adds / movs / bics 等（S 位置 1）
    if len(mn) > 2 and mn.endswith('s') and mn[:-1] in (
            'and', 'eor', 'sub', 'rsb', 'add', 'adc', 'sbc', 'rsc',
            'tst', 'teq', 'cmp', 'cmn', 'orr', 'mov', 'bic', 'mvn'):
        return _dp(mn[:-1], cond, 1, rest)
    # 单目移位指令：asr/lsl/lsr/ror Rd, Rm, #imm ≡ mov Rd, Rm, shift #imm
    if mn in ('asr', 'lsl', 'lsr', 'ror'):
        args = [a.strip() for a in rest.split(',')]
        if len(args) != 3 or not args[2].startswith('#'):
            raise Unsupported('%s form %r' % (mn, rest))
        rd, rm, sh = _reg(args[0]), _reg(args[1]), int(args[2].lstrip('#'), 0)
        if not (0 <= sh <= 31):
            raise Unsupported('%s shift %d' % (mn, sh))
        return ((cond << 28) | (13 << 21) | (rd << 12)
                | (sh << 7) | (_SHIFT_TYPES[mn] << 5) | rm)
    raise Unsupported('mnemonic %r' % mn_all)


def assemble_lines(lines, base):
    """汇编去掉注释/空行后的行列表（与 armasm.assemble 的预处理输出一致），返回 32 位字列表。

    支持 'label:' 前缀（附在指令行上）。任何不认识的形态抛 Unsupported。
    """
    instrs = []          # (index_in_output, mnemonic_line)
    labels = {}
    for raw in lines:
        line = raw.strip()
        while True:
            m = _LABEL.match(line)
            if not m:
                break
            labels[m.group(1)] = base + 4 * len(instrs)
            line = m.group(2).strip()
        if line:
            instrs.append(line)
    out = []
    for i, line in enumerate(instrs):
        at = base + 4 * i
        m = _LABEL.match(line)
        if m:  # 单行多标号：先记录再汇编剩余部分
            labels.setdefault(m.group(1), at)
            line = m.group(2).strip()
            if not line:
                continue
        try:
            out.append(_parse_one(line, at, labels) & 0xFFFFFFFF)
        except Unsupported as e:
            raise Unsupported('line %d %r: %s' % (i, line, e))
        except Exception as e:
            raise Unsupported('line %d %r: %s' % (i, line, e))
    return out
