# ceiling estimate: add a neutral-preserving 3x3 applied after the curves (gamma domain) to a fixed fit
import sys, json; sys.path.insert(0, '.')
import numpy as np
from scipy.optimize import least_squares
from cube_fit import samples, warm_samples, load_target, model, M_from, de2000
L, w, chart = samples(boost=4)
for p in sys.argv[1:]:
    f = json.load(open(p)); M = np.array(f['matrix']); cv = [np.array(c) for c in f['presets'][0]['curves']]
    T = load_target(f['presets'][0]['spec'], 'vlog', 0)
    m = model(M, cv, L); t = T(L)
    res = lambda q: (np.sqrt(w)[:, None] * (np.clip(m @ M_from(q).T, 0, 1) - t)).ravel()
    q = least_squares(res, np.zeros(6), x_scale=0.05).x
    warm = warm_samples(n=1200, seed=11); Lg, _, _ = samples(seed=7); g = Lg[600:]
    for nm, X in (('warm', warm), ('general', g)):
        a = model(M, cv, X); b = np.clip(a @ M_from(q).T, 0, 1); tt = T(X)
        print(p.split('/')[-1], nm, f'{de2000(a, tt).mean():.2f} -> {de2000(b, tt).mean():.2f}')
