"""Films v3 on camera (photo-ma5 chart shots): camera JPG vs v3 model vs spektrafilm target, per patch."""
import sys, json; sys.path.insert(0, '.')
import numpy as np, colour
from scipy.optimize import least_squares
from cube_fit import BASE, STD_LOOK, load_target, model, de2000
z = np.load('scratch/ma5/patches.npz'); J = z['jpg']; LIN = z['lin']
names = list(z['names'])
bg = lambda idx: np.interp(np.clip(idx, 0, 255), np.arange(256), BASE) / 16384
lin0, std = LIN[0].reshape(-1, 3), J[0].reshape(-1, 3)
ok = (std.max(1) < 0.95) & (std.min(1) > 0.03)
a = least_squares(lambda a: (bg(lin0[ok] @ a.reshape(3, 3).T) - std[ok]).ravel(), (STD_LOOK * 40).ravel()).x.reshape(3, 3)
print('Standard model fit: dE %.2f (patches used %d)' % (de2000(bg(lin0 @ a.T)[ok], std[ok]).mean(), ok.sum()))
EK = np.linalg.inv(STD_LOOK) @ a
V2 = 'work/films/'; V3 = 'work/films_v3/fits/'
films = [('R0011791', 'Ektar 100 (Vivid)', V2 + 'ektar100_portraendura.json', V3 + 'ektar_b1n3.json'),
         ('R0011794', 'Gold 200 (Retro)', V2 + 'gold200_portraendura.json', V3 + 'gold_b4n3.json'),
         ('R0011795', 'Pro 400H (HDR)', V2 + 'pro400h_on_gold_curves.json', V3 + 'pro400h_b2n3.json'),
         ('R0011796', 'Portra 400 (Cross)', V2 + 'portra400_portraendura.json', V3 + 'portra_b4n3.json')]
def run(p, L):
    f = json.load(open(p)); return model(np.array(f['matrix']), [np.array(c) for c in f['presets'][0]['curves']], L), f['presets'][0]['spec']
lab = lambda x: colour.XYZ_to_Lab(colour.sRGB_to_XYZ(np.clip(x, 0, 1)))
for n, name, v2, v3 in films:
    k = names.index(n); cam = J[k].reshape(-1, 3)
    L = LIN[k].reshape(-1, 3) @ EK.T * 0.18 / 7.8
    m3, spec = run(v3, L); m2, _ = run(v2, L); t = load_target(spec, 'vlog', 0)(L)
    use = (cam.max(1) < 0.97) & (t.min(1) > 0.02) & (cam.min(1) > 0.02)
    tl = lab(t); C = np.hypot(tl[:, 1], tl[:, 2]); h = np.degrees(np.arctan2(tl[:, 2], tl[:, 1])) % 360
    warm = use & (C > 20) & (h > 30) & (h < 100)
    def hue_err(x):
        xl = lab(x); return (((np.degrees(np.arctan2(xl[:, 2], xl[:, 1])) - np.degrees(np.arctan2(tl[:, 2], tl[:, 1]))) + 180) % 360 - 180)[warm].mean()
    d = lambda x, y, m: de2000(x[m], y[m]).mean()
    print(f'{name}: {use.sum()} patches ({warm.sum()} warm)')
    print(f'   camera vs v3 model  dE {d(cam, m3, use):.2f}   (firmware does what the model says)')
    print(f'   camera vs target    dE {d(cam, t, use):.2f}   warm {d(cam, t, warm):.2f}   warm hue err {hue_err(cam):+.1f} deg')
    print(f'   v3 model vs target  dE {d(m3, t, use):.2f}   warm {d(m3, t, warm):.2f}   warm hue err {hue_err(m3):+.1f} deg')
    print(f'   v2 model vs target  dE {d(m2, t, use):.2f}   warm {d(m2, t, warm):.2f}   warm hue err {hue_err(m2):+.1f} deg')
