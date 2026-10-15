"""Scene dE split by region (neutral / warm saturated / other) for v2 vs v3 fits on photo-test2."""
import sys, json; sys.path.insert(0, '.')
import numpy as np, rawpy, cv2, colour
from cube_fit import load_target, model, de2000
D = '../photo-test2/'
EK = np.load('scratch/pt2/EK.npy'); GAIN = 2 ** 1.0055
F = [(a.split()[0], a.split()[1], a.split()[2], a.split()[3]) for a in sys.argv[1:]]
for n, name, v2, v3 in F:
    with rawpy.imread(D + n + '.DNG') as r:
        lin = r.postprocess(use_camera_wb=True, output_color=rawpy.ColorSpace.sRGB, gamma=(1, 1), no_auto_bright=True, output_bps=16, half_size=True, user_flip=0).astype(np.float32) / 65535
    H, W = lin.shape[:2]; y0 = (H - 2000) // 2; x0 = (W - 3000) // 2
    lin = cv2.resize(lin[y0:y0 + 2000, x0:x0 + 3000], (720, 480), interpolation=cv2.INTER_AREA)
    L = (lin.reshape(-1, 3).astype(float) * GAIN) @ EK.T * 0.18 / 7.8
    res = {}
    for tag, p in (('v2', v2), ('v3', v3)):
        f = json.load(open(p)); m = model(np.array(f['matrix']), [np.array(c) for c in f['presets'][0]['curves']], L)
        t = load_target(f['presets'][0]['spec'], 'vlog', 0)(L); res[tag] = (m, t)
    t = res['v2'][1]; lab = colour.XYZ_to_Lab(colour.sRGB_to_XYZ(t)); C = np.hypot(lab[:, 1], lab[:, 2]); h = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360
    regions = {'neutral (C<8)': C < 8, 'warm sat (C>25, h 30-100)': (C > 25) & (h > 30) & (h < 100), 'other': ~((C < 8) | ((C > 25) & (h > 30) & (h < 100)))}
    out = []
    for rn, mk in regions.items():
        out.append(f"{rn} {mk.mean()*100:.0f}%: {de2000(res['v2'][0][mk], t[mk]).mean():.2f}->{de2000(res['v3'][0][mk], t[mk]).mean():.2f}")
    print(name, ' | '.join(out))
