"""Films v10 on camera (photo-v10 hue chart): camera JPG vs v10 model (curves, then post matrix via CSP) vs target.
Usage (from re-tools): check_v10.py"""
import sys, json; sys.path.insert(0, '.'); sys.path.insert(0, 'work/films_v8')
import numpy as np
from scipy.optimize import least_squares
from cube_fit import BASE, STD_LOOK, load_target, model, de2000
from chart import load
from film_cave import knots_of, expand
D = '../photo-v10/'
bg = lambda idx: np.interp(np.clip(idx, 0, 255), np.arange(256), BASE) / 16384
Js, Ls = load(D + 'R0011890')
lin0, std = Ls.reshape(-1, 3), Js.reshape(-1, 3)
ok = (std.max(1) < 0.95) & (std.min(1) > 0.03)
a = least_squares(lambda a: (bg(lin0[ok] @ a.reshape(3, 3).T) - std[ok]).ravel(), (STD_LOOK * 40).ravel()).x.reshape(3, 3)
print('Standard model fit: dE %.2f (patches used %d)' % (de2000(bg(lin0 @ a.T)[ok], std[ok]).mean(), ok.sum()))
EK = np.linalg.inv(STD_LOOK) @ a
F9, F10 = 'work/films_v9/fits/', 'work/films_v10/fits/'
films = [('R0011891', 'Ektar 100 (Vivid)', F9 + 'ektar_b1n3_joint.json'), ('R0011895', 'Gold 200 (Retro)', F9 + 'gold_b4n3_joint.json'),
         ('R0011896', 'Pro 400H (HDR)', F9 + 'pro400h_own_b4n3_joint.json'), ('R0011897', 'Portra 400 (Cross)', F9 + 'portra_b4n3_joint.json'),
         ('R0011894', 'Vision3 250D (Bleach)', F10 + 'vision3250d_2383_b4n3_joint.json')]
r = np.repeat(np.arange(7), 36)
perrow = lambda e, k: ' '.join(f'{e[k & (r == i)].mean():5.2f}' for i in range(7))
data = {}
for n, name, fp in films:
    J, Lr = load(D + n)
    cam = J.reshape(-1, 3); L = Lr.reshape(-1, 3) @ EK.T * 0.18 / 7.8
    f = json.load(open(fp))
    cv = [np.array(c) for c in f['presets'][0]['curves']]
    if 'Bleach' in name:
        cv = [expand(knots_of(c)) for c in cv]
    P = np.array(f.get('post_q512', f.get('cca1_q512'))) / 512
    m = np.clip(model(np.array(f['matrix']), cv, L) @ P.T, 0, 1)
    t = load_target(f['presets'][0]['spec'], 'vlog', 0)(L)
    use = (cam.max(1) < 0.97) & (t.min(1) > 0.02) & (cam.min(1) > 0.02)
    data[name] = (cam, m, t, use, L, f)
    print(f'{name}: {use.sum()} patches')
    print(f'   camera vs v10 model dE {de2000(cam, m)[use].mean():.2f}   rows {perrow(de2000(cam, m), use)}')
    print(f'   camera vs target    dE {de2000(cam, t)[use].mean():.2f}   rows {perrow(de2000(cam, t), use)}')
    print(f'   model  vs target    dE {de2000(m, t)[use].mean():.2f}')
