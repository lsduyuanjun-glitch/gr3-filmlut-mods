"""Verify the native-grain gate fix (make_grain_native.patch_gate) against the stock firmware.

The gate function 0x535131C0 sets plan+0x24 (the Shading/Clarity/Grain stage enable).  Stock gives 0
for tones 25+ (films); the fix makes them follow the Monotone rule (enabled if Shading/Clarity != 4
or Grain != 0).  Stock tones must stay identical.

Usage: python verify_grain_gate.py stock.bin patched.bin [n_films]
"""
import sys, struct
import codec_path  # noqa: F401
from emu import Emu
from gr4_editor.codec.container import inspect_container
from gr4_editor.codec.frames import decode_payload, section_rows
import make_slots15 as M15

GATE = 0x535131C0          # sets plan+0x24
n = int(sys.argv[3]) if len(sys.argv) > 3 else 4

ok = True
def check(cond, msg):
    global ok
    ok &= bool(cond)
    print(('OK   ' if cond else 'FAIL ') + msg)


def rtos_of(path):
    d = open(path, 'rb').read()
    i = inspect_container(d)
    dec, _ = decode_payload(d[128:i['payload_end']], i['decoded_size'])
    rows = {r['name']: r for r in section_rows(dec)}
    return bytes(dec[rows['RTOS']['start'] + 16:rows['RTOS']['end']])


def gate_result(rtos, tone, shading=4, clarity=4, grain=0):
    """Emulate the gate for one (tone, shading, clarity, grain) and return plan+0x24."""
    e = Emu(rtos)
    plan = e.alloc(0x40)
    si = e.alloc(0x800)
    e.w8(si + 0x77C, tone)
    e.w8(si + 0x793, shading)
    e.w8(si + 0x794, clarity)
    e.w8(si + 0x795, grain)
    e.call(GATE, plan, si)
    return e.u.mem_read(plan + 0x24, 1)[0]


S = rtos_of(sys.argv[1])
P = rtos_of(sys.argv[2])

# stock tones 11..22 unchanged across shading/clarity/grain combos
combos = [(4, 4, 0), (4, 4, 3), (0, 4, 0), (4, 0, 0), (0, 0, 1)]
all_stock_ok = True
for t in range(11, 23):
    for sh, cl, gr in combos:
        if gate_result(S, t, sh, cl, gr) != gate_result(P, t, sh, cl, gr):
            all_stock_ok = False
            check(False, f'stock tone {t} (sh={sh},cl={cl},gr={gr}) differs')
            break
check(all_stock_ok, 'stock tones 11-22 gate identical to stock over shading/clarity/grain combos')

# films 25..25+n-1: stock gives 0 always; fixed gives Monotone rule (1 if shading/clarity != 4 or grain != 0)
films_ok = True
for k in range(n):
    tone = 25 + k
    # stock: always 0
    for sh, cl, gr in combos:
        if gate_result(S, tone, sh, cl, gr) != 0:
            films_ok = False
            check(False, f'stock film tone {tone} not 0 (sh={sh},cl={cl},gr={gr})')
            break
    # fixed: Monotone rule
    exp_off = gate_result(P, tone, 4, 4, 0) == 0
    exp_grain = gate_result(P, tone, 4, 4, 3) == 1
    exp_shading = gate_result(P, tone, 0, 4, 0) == 1
    exp_clarity = gate_result(P, tone, 4, 0, 0) == 1
    if not (exp_off and exp_grain and exp_shading and exp_clarity):
        films_ok = False
        check(False, f'film tone {tone}: off={exp_off} grain={exp_grain} shading={exp_shading} clarity={exp_clarity} (expect all True)')
check(films_ok, f'films 25..{25+n-1}: stock always 0, fixed follows Monotone rule')

# a film with default params must NOT enable the stage (Off grain, neutral shading/clarity)
check(gate_result(P, 25, 4, 4, 0) == 0, 'film tone 25 with defaults does not enable the stage')

print()
print('ALL OK' if ok else 'FAILURES PRESENT')
sys.exit(0 if ok else 1)
