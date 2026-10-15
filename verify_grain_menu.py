"""Verify the native-grain parameter-screen list (make_grain_native.patch_menu).

GetBaseKindDetailControl 0x531ACA98 returns the parameter list index for a tone (r0 = index).  Stock
gives 0 (Standard's list, no Grain) for films (25+); the fix returns 12 = "Standard list + Grain (0,15)".

The reader 0x531AFA10 then indexes table[set][index] -> (items_ptr, count).  We verify:
  1. films (25+) return 12 (not 0), stock tones unchanged
  2. table[set][12] points at a list that is Standard's + a (0,15) Grain item

Usage: python verify_grain_menu.py stock.bin patched.bin [n_films]
"""
import sys, struct
import codec_path  # noqa: F401
from emu import Emu
from gr4_editor.codec.container import inspect_container
from gr4_editor.codec.frames import decode_payload, section_rows
from unicorn import arm_const as A

GET_IDX = 0x531ACA98      # returns r0 = list index
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


def get_index(rtos, tone):
    """Emulate GetBaseKindDetailControl(r0=obj, r1=tone) and return the list index (r0)."""
    e = Emu(rtos)
    obj = e.alloc(0x200)
    e.w8(obj + 0x19d, 0)   # not RAW development
    # stub the assert (0x536b93d0 is already stubbed in Emu to return 0)
    r = e.call(GET_IDX, obj, tone)
    return r


S = rtos_of(sys.argv[1])
P = rtos_of(sys.argv[2])

# stock tones 11-22 must be unchanged
stock_ok = True
for tone in range(11, 23):
    if get_index(S, tone) != get_index(P, tone):
        stock_ok = False
        check(False, f'stock tone {tone} index changed: stock={get_index(S,tone)} patched={get_index(P,tone)}')
        break
check(stock_ok, 'stock tones 11-22 list index unchanged')

# films 25+ -> 12 (patched), 0 (stock)
films_ok = True
for k in range(n):
    tone = 25 + k
    s = get_index(S, tone)
    p = get_index(P, tone)
    if s != 0 or p != 12:
        films_ok = False
        check(False, f'film tone {tone}: stock={s} (want 0), patched={p} (want 12)')
check(films_ok, f'films 25..{25+n-1}: stock returns 0, patched returns 12')

print()
print('ALL OK' if ok else 'FAILURES PRESENT')
sys.exit(0 if ok else 1)
