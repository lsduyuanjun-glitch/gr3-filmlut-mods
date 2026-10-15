"""Native grain engine for films (FINDINGS §45-48): enable GR3's built-in Particle (grain) for the
appended films (tones 25+).

This is the reverse-engineered reimplementation of the author's v27-v30 grain work, whose build
scripts were never committed to GitHub (only FINDINGS.md has the specs).  We implement the minimal
closed loop:

  1. grain value storage + menu  -> SetParticle / GetDefaultValueParticle film branch (UI Off/Low/Mid/High)
  2. pipeline pass-through       -> films carry SI+0x795 into ctx (not forced 0 like Standard)
  3. effect-stage gate           -> tone 25+ follows the Monotone rule (FINDINGS §47 v29)

Grain levels (native): 0 = Off, 3 = Low, 2 = Mid, 1 = High  (smaller = heavier grain).

Author's v27-v30 was layered on v24 (space extension) + v26 (per-film slider banks).  We keep the
scope minimal: the gate fix (3) needs only ~20 B and fits the v16 free regions; the value storage
and pass-through (1, 2) use the grown extension (see Image.grow).
"""
import struct
from make_slots15 import Space, code, put, B, BL
from armasm import assemble

# --- shared allocator -----------------------------------------------------
# All grain stubs (gate / pipeline / SetParticle / GetDefaultValueParticle) MUST share one Space,
# allocated sequentially, or they collide.  We reuse the SAME Space object the v16 build already used
# (M15.FALLBACK[0], the curve/knots `kspace`) so `Space.take()` keeps the allocation cursor and never
# overwrites the v16 stubs (e.g. the shooting `sh` proxy stub that patch_rawdev placed there).  A
# fresh `Space(free_left)` would re-run the cursor from the start and clobber those v16 stubs.
import make_slots15 as _M15
_GRAIN_SPACE = None


def _grain_space(info):
    """The v16 kspace (M15.FALLBACK[0]), shared with patch_rawdev so allocations never collide."""
    global _GRAIN_SPACE
    if _GRAIN_SPACE is None:
        _GRAIN_SPACE = _M15.FALLBACK[0]
    return _GRAIN_SPACE


def _reset_space():
    global _GRAIN_SPACE
    _GRAIN_SPACE = None

# --- effect-stage gate (FINDINGS §47) -----------------------------------
# 0x535131C0 decides plan+0x24 (the Shading/Clarity/Grain stage).  Films (25+) currently fall to
# `mov r3,#0` at 0x53513210 -> stage disabled.  v29: make tone 25+ follow the Monotone rule 0x53513240.
GATE_MOV = 0x53513210          # `mov r3,#0` (0xE3A03000)
GATE_RULE_MONO = 0x53513240    # reads SI+0x793/0x794/0x795, enables stage if any non-default
GATE_WRITE = 0x53513238        # `strb r3,[r0,#0x24]; bx lr` (the stock write-and-return)

GATE_MOV_ENC = 0xE3A03000      # mov r3, #0


def gate_stub_src(first_tone, n):
    """stub: tone in r1+0x77C; tone in [first_tone, first_tone+n) -> Monotone rule, else stock (mov 0).

    r3 is a scratch register in the caller (the gate function reads it fresh from r1+0x77C), so no
    save/restore is needed: on the film path we branch to the Monotone rule which re-reads r1; on the
    non-film path we set r3=0 exactly as the replaced `mov r3,#0` did.
    """
    return f'''
        ldrb r3, [r1, #0x77c]
        cmp r3, #{first_tone}
        blo N
        cmp r3, #{first_tone + n}
        bhs N
        b abs({GATE_RULE_MONO:#x})
    N:  mov r3, #0
        b abs({GATE_WRITE:#x})
    '''


# --- pipeline pass-through (FINDINGS §45 "Standard's case writes 0 ... to ctx+0x1F8") ---
# Standard case 0x536DBAA4 copies SI+0x793(Shading)->ctx+0x1F4, SI+0x794(Clarity)->ctx+0x1F6, but
# writes 0 to ctx+0x1F8 (Grain).  `0x536dbb58: strh r1,[ip]` where r1==0 and ip==ctx+0x1F8.
# Fix: carry SI+0x795 through.  Standard's own SI+0x795 is always 0 (no setter path), so this is
# byte-identical for Standard and only the films (which we give a Grain setter) become non-zero.
PT_STRH = 0x536DBB58          # strh r1,[ip]  (r1=0, ip=ctx+0x1F8); replace with BL stub
PT_STRH_ENC = 0xE1CC10B0      # strh r1,[ip]  (ip = r12)


def pipeline_stub_src(_base=None):
    """Read SI+0x795 into ctx+0x1F8.  r3=SI, ip=ctx+0x1F8 on entry (caller-saved, untouched by BL).

    Uses r2 as scratch (r2 is dead at this point in the Standard case: the next uses are
    `movw r7/r5` and `strh r1,[...]` which set their own registers).  r1 must stay 0 for the
    trailing `strh r1,[r0,r7]` / `strh r1,[r8]` / `strh r1,[r0,r5]` writes.
    """
    return f'''
        ldrb r2, [r3, #0x795]
        strh r2, [ip]
        bx lr
    '''


def patch_pipeline(img, films, info):
    """2. pipeline pass-through: ctx+0x1F8 <- SI+0x795 (films keep grain; Standard unchanged)."""
    assert img.word(PT_STRH) == PT_STRH_ENC, hex(img.word(PT_STRH))
    sp = _grain_space(info)
    at = code(sp, img, 'grain pipeline', pipeline_stub_src)
    put(img, PT_STRH, BL(PT_STRH, at), PT_STRH_ENC)
    return dict(pipeline=hex(at), space=[(nm, hex(a), sz) for nm, a, sz in sp.used])


def _free_regions(info, min_sz):
    free = []
    for a, b in info['_code']['free_left']:
        lo, hi = int(a, 16), int(a, 16) + b
        if hi - lo >= min_sz:
            free.append((lo, hi))
    return free


# --- grain value storage + menu (FINDINGS §45 "v27 Grain") ----------------
# SetParticle 0x532C1780 / GetDefaultValueParticle 0x532C9744 dispatch on `type` (the value returned
# by 0x532bd6d4) — the grain has THREE independent parameters, each stored in its own SI field:
#   type 0 -> SI+0x29a   (grain "level/on-off" — the value list 0x53B590D8 = [0,3,2,1] Off/Low/Mid/High)
#   type 1 -> SI+0x37c   (grain "strength/type" second axis)
#   type 2 -> SI+0x45e   (grain "intensity" main value)
# Each type has its own tone jump-table (tone 13..22) and its own default branch for tone 25+:
#   SetParticle defaults      : type0 0x532c18c0 / type1 0x532c1888 / type2 0x532c17f0  (all `b 0x532c1844` no-op)
#   GetDefaultValueParticle   : type0 0x532c983c / type1 0x532c9874 / type2 0x532c979c  (assert -> 0)
# The Monotone (tone 13) branches tail-call a per-type write fn:
#   type0 -> 0x5325dc3c (strb r1,[r3,#0x29a]; sync setter)   type1 -> 0x532601cc (0x37c)   type2 -> 0x5326276c (0x45e)
# and read back via GetDefault mono: type0 0x532c9930(0x29a) type1 0x532c98e0(0x37c) type2 0x532c9980(0x45e).
#
# The earlier build only patched type 2 (SI+0x45e), so the film menu showed a Grain item but only ONE
# selectable step (the value list for type 0/1 was never populated).  We patch ALL THREE types so the
# film gets the full Off/Low/Mid/High enum, matching Monotone.
SETTER = 0x5354C570            # property 0xC3 setter (writes SI+0x795)
SP_NOOP = 0x532C1844           # SetParticle no-op epilogue (shared by all three default branches)
SP_DEFAULTS = {0: (0x532C18C0, 0xEAFFFFDF), 1: (0x532C1888, 0xEAFFFFED), 2: (0x532C17F0, 0xEA000013)}
GDP_READ_OFF = {0: 0x29A, 1: 0x37C, 2: 0x45E}                  # per-type SI field read by GetDefault mono
GDP_MONO_READ = 0x532406FC     # returns SI object pointer (in r0)
GDP_ASSERT = 0x532C9990        # GetDefaultValueParticle assert default (returns 0)
GDP_EPILOG = 0x532C97F4        # GetDefaultValueParticle common epilogue (sub sp,fp,#0x18; ldm)
GDP_DEFAULTS = {0: (0x532C983C, 0xEA00006B), 1: (0x532C9874, 0xEA000051), 2: (0x532C979C, 0xEA00007B)}


def setparticle_stub_src(n, t):
    """SetParticle film branch for ONE type: on entry r5 = tone-13 (>=12 for films), r6 = value,
    r0 = 0x5320b31c's return (an object whose +4 is the SI pointer).

    The per-type Monotone write fn stores the field BUT gates the 0xC3 setter call behind a
    "is this Monotone?" check (type0: [si+0x1c0]&~0xff00ff==0xd0000; type1: [si+0x1c0]==1&&[si+0x1c4]==0xd;
    type2: 0x53262738) which is false for films — so the field would be written but SI+0x795 never
    synced.  We therefore replicate the store + unconditional setter inline (the same sequence the
    write fns use after their check passes), skipping the gate for films.
    """
    off = {0: 0x29A, 1: 0x37C, 2: 0x45E}[t]
    return f'''
        cmp r5, #12
        blo N
        cmp r5, #{12 + n}
        bhs N
        push {{r4, lr}}
        mov r4, r0
        ldr r3, [r4, #4]
        strb r6, [r3, #{off}]
        mov r0, r4
        bl abs(0x53525d5c)
        ldr r0, [r0]
        mov r1, r6
        bl abs({SETTER:#x})
        pop {{r4, lr}}
        b abs({SP_NOOP:#x})
    N:  b abs({SP_NOOP:#x})
    '''


def getdefault_stub_src(n, t):
    """GetDefaultValueParticle film branch for ONE type: r5 = tone-13, r6 = SI object (from 0x5320b31c).
    Films read the type's SI field like Monotone; everyone else keeps the original assert.
    """
    return f'''
        cmp r5, #12
        blo N
        cmp r5, #{12 + n}
        bhs N
        mov r0, r6
        bl abs({GDP_MONO_READ:#x})
        ldrb r0, [r0, #{GDP_READ_OFF[t]}]
        b abs({GDP_EPILOG:#x})
    N:  b abs({GDP_ASSERT:#x})
    '''


def patch_storage(img, films, info):
    """1. grain value storage: films read/write all THREE grain fields (0x29a/0x37c/0x45e) via the
    Monotone path, so the menu shows the full Off/Low/Mid/High enum (not just one step)."""
    sp = _grain_space(info)
    n = len(films)
    out = {}
    for t in (0, 1, 2):
        sp_def, sp_def_enc = SP_DEFAULTS[t]
        gdp_def, gdp_def_enc = GDP_DEFAULTS[t]
        assert img.word(sp_def) == sp_def_enc, (hex(sp_def), hex(img.word(sp_def)))
        assert img.word(gdp_def) == gdp_def_enc, (hex(gdp_def), hex(img.word(gdp_def)))
        # a dedicated stub per type (they share the grain Space, allocated sequentially)
        sp_at = code(sp, img, f'grain setparticle t{t}', lambda base, t=t: setparticle_stub_src(n, t))
        gd_at = code(sp, img, f'grain getdefault t{t}', lambda base, t=t: getdefault_stub_src(n, t))
        put(img, sp_def, B(sp_def, sp_at), sp_def_enc)
        put(img, gdp_def, B(gdp_def, gd_at), gdp_def_enc)
        out[f'setparticle_t{t}'] = hex(sp_at)
        out[f'getdefault_t{t}'] = hex(gd_at)
    out['space'] = [(nm, hex(a), sz) for nm, a, sz in sp.used]
    return out


def patch_gate(img, films, info):
    """3. effect-stage gate: tone 25+ -> Monotone rule. Uses the v16 free space (no growth needed).

    `info` is make_slots15.patch's return dict; its `_code.space` lists every region the v16 build
    already used, so we can pick a still-free region for our ~32 B stub.
    """
    assert img.word(GATE_MOV) == GATE_MOV_ENC, hex(img.word(GATE_MOV))
    # remaining free regions after the v16 build (space/free_left as (hex, size))
    sp = _grain_space(info)
    n = len(films)
    at = code(sp, img, 'grain gate', lambda base: gate_stub_src(25, n))
    put(img, GATE_MOV, B(GATE_MOV, at), GATE_MOV_ENC)
    return dict(gate=hex(at), space=[(nm, hex(a), sz) for nm, a, sz in sp.used])


# --- parameter-screen list (FINDINGS §45 "films -> index 12") ------------
# The Image Control parameter screen picks its item list by `index` (tone-11).  Films (25+) fall to
# 0x531acbbc (assert + return 0 = Standard's list), which has NO Grain item.  We give films their own
# list index 12 = "Standard's list of the set + (0,15) Grain", so the film menu shows the standard
# colour params (sat/hue/key/contrast/HL/shadow/sharp/shading/clarity) PLUS a Grain control.
#
# The list table 0x53B3488C is [3 set][12 index] of 8-byte entries (items_ptr, count_u16).  It is
# immediately followed by the item arrays (no room to grow in place), so we rebuild the whole table
# as [3][13] in the grown extension, append the three new item arrays, then point the 4 readers at
# the new table and widen their `mla 12` to 13, and make the film branch return 12.

TABLE_AT = 0x53B3488C            # stock [3][12] list table
MENU_IDX = 12                    # films' list index (the new 13th column)
# The v16 shooting GetBaseKindDetailControl 0x531ACA98 routes the film list index through a proxy stub:
#   0x531ACB1C `cmp r4,#0xb` was replaced by make_slots16.patch_rawdev with `bl <sh stub>` (SH_KIND); the stub
#   maps film r4 (14..17) -> proxy_tab[0] = 0 via `ldrb r4,[ip,r4]`, so films return jump-table[0] = `mov r0,#0`
#   (Standard's list) and NEVER reach the assert default 0x531ACBBC.  To give films their own list index 12 we
#   (a) turn the stub's film `ldrb` into `mov r4,#0x1f` (a film sentinel no stock tone produces), and
#   (b) repoint `0x531ACB24 b 0x531ACBBC` (the r4>11 fall-through) at a stub that returns 12 for r4==0x1f and
#   otherwise keeps the stock assert.  This avoids both the assert path and clobbering Standard.
SH_KIND = 0x531ACB1C            # `bl <sh stub>` (was stock `cmp r4,#0xb` 0xE354000B)
SH_LDRB_AT_OFF = 5              # the stub's film `ldrb r4,[ip,r4]` sits 5 words after the stub entry
SH_LDRB_ENC = 0xE7DC4004        # `ldrb r4, [ip, r4]`
SH_MOV_SENT = 0xE3A0401F        # `mov r4, #0x1f`  (film sentinel; 0x1f = 31 > 11, no tone yields it)
MENU_FALL = 0x531ACB24          # `b 0x531ACBBC` (r4 > 11 fall-through after the jump table)
MENU_FALL_ENC = 0xEA000024      # `b #0x531acbbc`
MENU_ASSERT = 0x531ACBBC        # stock film default: assert + return 0 (kept for genuinely invalid tones)
MENU_EPILOG = 0x531ACB5C        # common epilogue `sub sp,fp,#0x18; ldm ...` (jump-table entries `mov r0,#N; b` here)

# 4 readers, each loads the table base via movw/movt and multiplies by 12 (mla lr/r2/ip, #0xc).
# (reader, (movw_at, movt_at), (mla_mov_at, mla_reg)) — the multiplier is an immediate in the `mov #0xc`.
READERS = [
    (0x531AFA10, (0x531AFA20, 0x531AFA24), (0x531AFA1C, 'lr')),   # mov lr,#0xc
    (0x531AFAB8, (0x531AFABC, 0x531AFACC), (0x531AFAC8, 'r2')),   # mov r2,#0xc
    (0x531AFF88, (0x531AFFA0, 0x531AFFA8), (0x531AFF98, 'lr')),   # mov lr,#0xc
    (0x531B01D0, (0x531B01F4, 0x531B01F8), (0x531B01EC, 'ip')),   # mov ip,#0xc
]


def _mov_enc(rd, imm):
    """mov rd,#imm (imm < 256)."""
    return 0xE3A00000 | (rd << 12) | imm


def _movw_enc(rd, v):
    return 0xE3000000 | (rd << 12) | ((v & 0xF000) << 4) | (v & 0xFFF)


def _movt_enc(rd, v):
    """movt rd,#imm16 where imm16 = high 16 bits of v (v is a full 32-bit value)."""
    return 0xE3400000 | (rd << 12) | ((v >> 16 & 0xF000) << 4) | (v >> 16 & 0xFFF)


def patch_menu(img, films, info):
    """5. parameter screen: films get their own list index 12 = Standard list + Grain (0,15).

    Requires the extension (img.grow) to be done first — build_firmware grows 64 KB before any patch.
    """
    ext = getattr(img, '_grain_ext', None)
    assert ext is not None, 'grow the image (img.grow) before patch_menu'
    ext_cur = getattr(img, '_grain_ext_cur', ext)
    ext_cur = (ext_cur + 7) & ~7          # 8-align

    # 2) build the three film item arrays (Standard list of the set + (0,15))
    def stock_items(set_i):
        off = TABLE_AT + (set_i * 12 + 0) * 8
        p = img.word(off); c = img.word(off + 4)
        return bytes(img.read(p, c * 2))
    item_addrs = []
    for set_i in range(3):
        arr = stock_items(set_i) + bytes([0, 15])      # append (visibility 0, id 15 = Grain)
        img.write(ext_cur, arr)
        item_addrs.append(ext_cur)
        ext_cur += len(arr)
        ext_cur = (ext_cur + 7) & ~7

    # 3) rebuild the table [3][13] in the extension: copy stock 12 columns, add column 12
    table_addr = ext_cur
    for set_i in range(3):
        for idx in range(12):
            src = TABLE_AT + (set_i * 12 + idx) * 8
            img.write(table_addr + (set_i * 13 + idx) * 8, img.read(src, 8))
        # new column 12: (item_addrs[set_i], count)
        count = (len(stock_items(set_i)) // 2) + 1
        img.write(table_addr + (set_i * 13 + 12) * 8,
                  struct.pack('<II', item_addrs[set_i], count))
    ext_cur = table_addr + 3 * 13 * 8

    # 4) point the 4 readers at the new table (movw/movt) and widen mla to 13
    for _reader, (mw, mt), (mm, reg) in READERS:
        # mw is `movw rd,#0x488c`, mt is `movt rd,#0x53b3` (same rd)
        mw_w = img.word(mw)
        rd = (mw_w >> 12) & 15
        assert (mw_w & 0x0FF00000) == 0x03000000, hex(mw_w)          # movw
        assert (img.word(mt) & 0x0FF00000) == 0x03400000, hex(img.word(mt))  # movt
        put(img, mw, _movw_enc(rd, table_addr & 0xFFFF), mw_w)
        put(img, mt, _movt_enc(rd, table_addr), img.word(mt))
        # the multiplier: `mov reg,#0xc`
        rreg = {'lr': 14, 'r2': 2, 'ip': 12}[reg]
        old = _mov_enc(rreg, 0xC)
        assert img.word(mm) == old, (hex(mm), hex(img.word(mm)))
        put(img, mm, _mov_enc(rreg, 0xD), old)

    # 5) films -> list index 12.  The v16 proxy stub already remaps films to index 0 (jump table -> `mov r0,#0`),
    #    so we instead make the stub emit a film sentinel (0x1f) and turn the r4>11 fall-through into a return-12.
    bl = img.word(SH_KIND)
    assert (bl & 0x0F000000) == 0x0B000000, hex(bl)          # `bl`
    off = bl & 0xFFFFFF
    if off & 0x800000:
        off -= 0x1000000
    sh = SH_KIND + 8 + (off << 2)                            # the v16 proxy stub entry address
    assert img.word(sh + 4 * SH_LDRB_AT_OFF) == SH_LDRB_ENC, (hex(sh), hex(img.word(sh + 4 * SH_LDRB_AT_OFF)))
    put(img, sh + 4 * SH_LDRB_AT_OFF, SH_MOV_SENT, SH_LDRB_ENC)   # film branch: `ldrb r4,[ip,r4]` -> `mov r4,#0x1f`

    # the fall-through (r4 > 11) now means "film (0x1f)" or "genuinely invalid tone (23/24)".  A small stub in
    # the grain space distinguishes them: 0x1f -> mov r0,#12 ; b epilogue ; else -> stock assert 0x531ACBBC.
    sp = _grain_space(info)
    film_idx = code(sp, img, 'grain film index', lambda base: f'''
        cmp r4, #0x1f
        moveq r0, #0xc
        beq abs({MENU_EPILOG:#x})
        b abs({MENU_ASSERT:#x})''')
    put(img, MENU_FALL, B(MENU_FALL, film_idx), MENU_FALL_ENC)

    img._grain_ext_cur = ext_cur
    return dict(ext=hex(ext), table=hex(table_addr),
                items=[hex(a) for a in item_addrs],
                sh=hex(sh), fallthrough=hex(film_idx))
