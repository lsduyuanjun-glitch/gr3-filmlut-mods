"""v2 fit | v3 fit | spektrafilm LUT, all rendered from the photo-test2 RAWs with the R2Y model."""
import sys, json; sys.path.insert(0, '.')
import numpy as np, rawpy, cv2
from PIL import Image, ImageDraw
from cube_fit import load_target, model, de2000
D = '../photo-test2/'
EK = np.load('scratch/pt2/EK.npy'); GAIN = 2 ** 1.0055
F = [('R0011740', 'Portra 400', 'work/films/portra400_portraendura.json', 'work/films_v3/fits/portra_b4n3.json'),
     ('R0011737', 'Ektar 100', 'work/films/ektar100_portraendura.json', 'work/films_v3/fits/ektar_b1n3.json'),
     ('R0011738', 'Gold 200', 'work/films/gold200_portraendura.json', 'work/films_v3/fits/gold_b4n3.json'),
     ('R0011739', 'Pro 400H', 'work/films/pro400h_on_gold_curves.json', 'work/films_v3/fits/pro400h_b2n3.json')]
Wd, Hd = 720, 480
def fitted(p, L):
    f = json.load(open(p)); return model(np.array(f['matrix']), [np.array(c) for c in f['presets'][0]['curves']], L), f['presets'][0]['spec']
rows = []
for n, name, v2, v3 in F:
    with rawpy.imread(D + n + '.DNG') as r:
        lin = r.postprocess(use_camera_wb=True, output_color=rawpy.ColorSpace.sRGB, gamma=(1, 1), no_auto_bright=True, output_bps=16, half_size=True, user_flip=0).astype(np.float32) / 65535
    H, W = lin.shape[:2]; y0 = (H - 2000) // 2; x0 = (W - 3000) // 2
    lin = cv2.resize(lin[y0:y0 + 2000, x0:x0 + 3000], (Wd, Hd), interpolation=cv2.INTER_AREA)
    L = (lin.reshape(-1, 3).astype(float) * GAIN) @ EK.T * 0.18 / 7.8
    a, spec = fitted(v2, L); b, _ = fitted(v3, L)
    t = load_target(spec, 'vlog', 0)(L)
    da, db = de2000(a, t).mean(), de2000(b, t).mean()
    panels = [x.reshape(Hd, Wd, 3) for x in (a, b, t)]
    sep = np.ones((Hd, 6, 3))
    im = Image.fromarray((np.clip(np.concatenate([panels[0], sep, panels[1], sep, panels[2]], 1), 0, 1) * 255).astype('u1'))
    dr = ImageDraw.Draw(im)
    for x, txt in ((0, f'{name} v2 (dE {da:.1f})'), (Wd + 6, f'{name} v3 (dE {db:.1f})'), (2 * Wd + 12, f'{name} spektrafilm target')):
        dr.rectangle([x, 0, x + 230, 16], fill=(0, 0, 0)); dr.text((x + 4, 2), txt, fill=(255, 255, 0))
    rows.append(np.asarray(im)); print(name, f'scene dE v2 {da:.2f} -> v3 {db:.2f}')
Image.fromarray(np.concatenate(rows, 0)).save('work/films_v3/compare_v2_v3_target.jpg', quality=90)
