import numpy as np

from apg_ppgbp import apg, correlacion, indices, ondas, parcial

FS = 100
t = np.arange(int(2.1 * FS)) / FS


def onda_apg(amplitudes, inicio=0.6):
    senal = np.zeros(t.size)
    for k, amplitud in enumerate(amplitudes):
        senal += amplitud * np.exp(-((t - inicio - 0.1 * k) / 0.03) ** 2)
    return senal


completa = onda_apg((1, -0.6, 0.15, -0.3, 0.1))
encontradas = ondas(completa, FS)
assert encontradas.shape == (1, 5), encontradas
assert np.allclose(encontradas[0], (1, -0.6, 0.15, -0.3, 0.1), atol=0.05), encontradas
ba, ca, da, ea, agi = indices(encontradas)[0]
assert abs(ba + 0.6) < 0.06 and abs(agi + 0.55) < 0.1, (ba, agi)

parcial_ab = ondas(onda_apg((1, -0.5)), FS)
assert np.isnan(parcial_ab[0, 2:]).all() and not np.isnan(parcial_ab[0, :2]).any()
assert np.isnan(indices(parcial_ab)[0, 4]) and abs(indices(parcial_ab)[0, 0] + 0.5) < 0.06

assert ondas(np.zeros(t.size), FS).shape == (0, 5)
assert ondas(np.zeros(20), FS).shape == (0, 5)

crudo = 2000 + 300 * np.sin(2 * np.pi * 1.2 * np.arange(2100) / 1000) ** 3 + np.arange(2100) * 0.1
resultado = apg(crudo, 100, 8)
assert resultado.shape == (210,) and np.isfinite(resultado).all()
assert np.allclose(resultado, apg(-crudo, 100, 8), atol=1e-6)
assert apg(crudo, 1000, 15).shape == (2100,)

generador = np.random.default_rng(0)
x = generador.normal(size=300)
y = 0.8 * x + 0.6 * generador.normal(size=300)
n, r, bajo, alto, rho = correlacion(x, y)
assert n == 300 and bajo < r < alto and 0.7 < r < 0.9 and 0.7 < rho < 0.9
x[:10] = np.nan
assert correlacion(x, y)[0] == 290

z = generador.normal(size=500)
a_, b_ = z + 0.3 * generador.normal(size=500), z + 0.3 * generador.normal(size=500)
assert correlacion(a_, b_)[1] > 0.8 and abs(parcial(a_, b_, z)) < 0.15

print("OK")
