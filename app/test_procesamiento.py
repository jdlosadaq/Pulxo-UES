import numpy as np

from lector import FS
from procesamiento import frecuencia_cardiaca, indice_perfusion, spo2

t = np.arange(30 * FS) / FS
ruido = np.random.default_rng(0).normal(0, 30, (2, t.size))

for lpm in (40, 72, 150):
    fase = t * lpm / 60 % 1
    onda = np.exp(-((fase - 0.18) / 0.08) ** 2) + 0.5 * np.exp(-((fase - 0.55) / 0.11) ** 2)
    rojo = 50000 - 500 * onda + ruido[0]
    ir = 60000 - 1200 * onda + ruido[1]

    assert abs(frecuencia_cardiaca(ir) - lpm) < 2, lpm
    assert abs(spo2(rojo, ir) - 97.5) < 0.5, lpm

seno = 60000 + 600 * np.sin(2 * np.pi * 72 / 60 * t) + ruido[1]
assert abs(indice_perfusion(seno) - 2.0) < 0.1

print("OK")
