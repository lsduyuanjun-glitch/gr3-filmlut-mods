"""Films v9 on camera (photo-v9 hue chart): camera JPG vs v9 model (curves + CCA1) vs v7 model vs spektrafilm target."""
import sys, json; sys.path.insert(0, '.'); sys.path.insert(0, 'work/films_v8')
import numpy as np, colour
from scipy.optimize import least_squares
from cube_fit import BASE, STD_LOOK, load_target, model, de2000
from chart import load
D = '../photo-v9/'
bg = lambda idx: np.interp(np.clip(idx, 0, 255), np.arange(256), BASE) / 16384
Js, Ls = load(D + 'R0011856')
lin0, std = Ls.reshape(-1, 3), Js.reshape(-1, 3)
ok = (std.max(1) < 0.95) & (std.min(1) > 0.03)
a = least_squares(lambda a: (bg(lin0[ok] @ a.reshape(3, 3).T) - std[ok]).ravel(), (STD_LOOK * 40).ravel()).x.reshape(3, 3)
print('Standard model fit: dE %.2f (patches used %d)' % (de2000(bg(lin0 @ a.T)[ok], std[ok]).mean(), ok.sum()))
EK = np.linalg.inv(STD_LOOK) @ a
mats = json.load(open('work/films_v9/cca1_mats.json'))
F3 = F4 = 'work/films_v9/fits/'
films = [('R0011857', 'Ektar 100 (Vivid)', F3 + 'ektar_b1n3_joint.json'), ('R0011860', 'Gold 200 (Retro)', F3 + 'gold_b4n3_joint.json'),
         ('R0011861', 'Pro 400H (HDR)', F4 + 'pro400h_own_b4n3_joint.json'), ('R0011862', 'Portra 400 (Cross)', F3 + 'portra_b4n3_joint.json')]
lab = lambda x: colour.XYZ_to_Lab(colour.sRGB_to_XYZ(np.clip(x, 0, 1)))
rows = []
for n, name, fp in films:
    J, Lr = load(D + n)
    cam = J.reshape(-1, 3); L = Lr.reshape(-1, 3) @ EK.T * 0.18 / 7.8
    f = json.load(open(fp))
    m7 = model(np.array(f['matrix']), [np.array(c) for c in f['presets'][0]['curves']], L)
    C = np.array(mats[fp]['q512']) / 512
    m8 = np.clip(m7 @ C.T, 0, 1)
    t = load_target(f['presets'][0]['spec'], 'vlog', 0)(L)
    use = (cam.max(1) < 0.97) & (t.min(1) > 0.02) & (cam.min(1) > 0.02)
    tl = lab(t); Ch = np.hypot(tl[:, 1], tl[:, 2]); h = np.degrees(np.arctan2(tl[:, 2], tl[:, 1])) % 360
    warm = use & (Ch > 20) & (h > 30) & (h < 100)
    def hue_err(x):
        xl = lab(x); return (((np.degrees(np.arctan2(xl[:, 2], xl[:, 1])) - np.degrees(np.arctan2(tl[:, 2], tl[:, 1]))) + 180) % 360 - 180)[warm].mean()
    d = lambda x, y, k: de2000(x[k], y[k]).mean()
    print(f'{name}: {use.sum()} patches ({warm.sum()} warm)')
    print(f'   camera vs v9 model  dE {d(cam, m8, use):.2f}   (no-CCA1 model) {d(cam, m7, use):.2f}')
    print(f'   camera vs target    dE {d(cam, t, use):.2f}   warm {d(cam, t, warm):.2f}   warm hue err {hue_err(cam):+.1f} deg')
    print(f'   v9 model vs target  dE {d(m8, t, use):.2f}   warm {d(m8, t, warm):.2f}   warm hue err {hue_err(m8):+.1f} deg')
    print(f'   v7 model vs target  dE {d(m7, t, use):.2f}   warm {d(m7, t, warm):.2f}   warm hue err {hue_err(m7):+.1f} deg')
