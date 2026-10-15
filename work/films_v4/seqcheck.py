"""v4: library pointers 6-8 are switched per call; check mode switching in one emulator session
(Retro -> HDR -> Retro -> Standard -> HDR -> Retro, still and live view) gives each mode its own curves."""
import sys, json; sys.path.insert(0, '.'); import codec_path  # noqa: F401
import numpy as np
from gr4_editor.codec.container import inspect_container
from gr4_editor.codec.frames import decode_payload
from run_tuning import setup, make
d = open(sys.argv[1], 'rb').read(); i = inspect_container(d)
dec, _ = decode_payload(d[128:i['payload_end']], i['decoded_size']); R = bytes(dec[0x10870:0x10c5e30])
fits = {19: json.load(open(sys.argv[2])), 20: json.load(open(sys.argv[3]))}
ok = True
for stage in (1, 0):
    e, obj, info, si = setup(stage=stage, rtos=R)
    g = e.r32(obj + 0x17c)
    u = lambda a: np.frombuffer(bytes(e.u.mem_read(a, 512)), '<u2').astype(int)
    for tone in (19, 20, 19, 11, 20, 19):
        make(e, obj, info, si, tone, stage=stage)
        if tone == 11: continue
        comp = [u(g + o) for o in (0x2a08, 0x2c08, 0x2e08)]; base = u(g)
        want = [np.interp(np.clip(base / 64, 0, 255), np.arange(256), np.array(c)) for c in fits[tone]['presets'][0]['curves']]
        err = max(np.abs(comp[c] - want[c]).max() for c in range(3)); ok &= err <= 2
        print(f'stage {stage} tone {tone}: curve err {err:.0f}')
print('ALL OK' if ok else 'FAIL')
