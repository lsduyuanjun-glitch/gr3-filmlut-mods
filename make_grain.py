"""Grain feel patch: strength (SI+0x793) x type (SI+0x794) dual patch.

Key insight (from real-shoot feedback): the Ricoh grain look = strength x type.
Patching only the strength makes grain extremely fine/almost invisible.
Type controls grain coarseness; +4 (raw 8) is the most visible.

Effect struct: [r4+0]=strength, [r4+2]=type.  Loader reads:
  strength: ldrb sl,[r3,#0x793]  = 0xE5D3A793   (sl = r10)
  type:     ldrb sb,[r3,#0x794]  = 0xE5D39794   (sb = r9, NOT r11/fp!)

Patch: replace each ldrb with mov reg,#imm (equal length, reversible):
  mov sl,#N = 0xE3A0A00N
  mov sb,#N = 0xE3A0900N

Read addresses (GR III 2.10 fwdc239b.bin), attributed by emulating ImageTuning Make per tone
(see work log 2026-10-12; each site executed only in its mode's Make path):
  strength: vivid/positive 0x536DB94C  standard 0x536DBAF4  monotone 0x536DBBD0
            bleach 0x536DBD68          retro 0x536DBE34     cross 0x536DBFA4   negative 0x536DC078
  type:     vivid/positive 0x536DB968  standard 0x536DBB10  monotone 0x536DBBE4
            bleach 0x536DBD8C          retro 0x536DBE54     cross 0x536DBFC4   negative 0x536DC094
HDR Tone has no grain site (Make never reads 0x793/0x794).
"""
import struct

STRENGTH_ADDR = dict(vivid=0x536DB94C, standard=0x536DBAF4, monotone=0x536DBBD0,
                      bleach=0x536DBD68, retro=0x536DBE34, cross=0x536DBFA4, negative=0x536DC078)
TYPE_ADDR     = dict(vivid=0x536DB968, standard=0x536DBB10, monotone=0x536DBBE4,
                      bleach=0x536DBD8C, retro=0x536DBE54, cross=0x536DBFC4, negative=0x536DC094)
ORIG_STRENGTH = 0xE5D3A793            # ldrb sl,[r3,#0x793]
ORIG_TYPE     = 0xE5D39794            # ldrb sb,[r3,#0x794]


def patch_grain(img, specs):
    """specs: {mode: {'strength': 0..8, 'type': 0..8}}  (4 = neutral for both).

    Returns {mode: {'strength_at': hex, 'type_at': hex, 'from': (s,t), 'to': (s,t)}}
    """
    done = {}
    for mode, sp in specs.items():
        if mode not in STRENGTH_ADDR:
            continue
        s_val = int(sp.get('strength', 4))
        t_val = int(sp.get('type', 4))
        assert 0 <= s_val <= 8 and 0 <= t_val <= 8
        sa, ta = STRENGTH_ADDR[mode], TYPE_ADDR[mode]
        old_s = img.word(sa)
        old_t = img.word(ta)
        # sanity: only patch the exact loader instructions we know
        if old_s != ORIG_STRENGTH or old_t != ORIG_TYPE:
            raise SystemExit(f'{mode}: unexpected instructions at grain site '
                             f'(strength={old_s:#x}, type={old_t:#x}) -- refusing to patch')
        img.write(sa, struct.pack('<I', 0xE3A0A000 | s_val))   # mov sl,#s_val
        img.write(ta, struct.pack('<I', 0xE3A09000 | t_val))   # mov sb,#t_val
        # verify read-back
        assert img.word(sa) == 0xE3A0A000 | s_val
        assert img.word(ta) == 0xE3A09000 | t_val
        done[mode] = {'strength_at': hex(sa), 'type_at': hex(ta),
                      'from': (old_s, old_t), 'to': (s_val, t_val)}
    return done
