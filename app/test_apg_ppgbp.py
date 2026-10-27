import numpy as np

from apg_ppgbp import correlacion, parcial, preparar

crudo = 2000 + 300 * np.sin(2 * np.pi * 1.2 * np.arange(2100) / 1000) ** 3 + np.arange(2100) * 0.1
resultado = preparar(crudo, 100, 8)
assert resultado.shape == (210,) and np.isfinite(resultado).all()
assert np.allclose(resultado, preparar(-crudo, 100, 8), atol=1e-6)
assert preparar(crudo, 1000, 15).shape == (2100,)

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
