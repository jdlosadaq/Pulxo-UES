import numpy as np

from lector import FS
from procesamiento import calidad_senal, frecuencia_cardiaca, indice_perfusion, spo2, variabilidad

t = np.arange(30 * FS) / FS
ruido = np.random.default_rng(0).normal(0, 30, (2, t.size))

for lpm in (40, 72, 150):
    fase = t * lpm / 60 % 1
    onda = np.exp(-((fase - 0.18) / 0.08) ** 2) + 0.5 * np.exp(-((fase - 0.55) / 0.11) ** 2)
    rojo = 50000 - 500 * onda + ruido[0]
    ir = 60000 - 1200 * onda + ruido[1]

    assert abs(frecuencia_cardiaca(ir) - lpm) < 2, lpm
    assert abs(spo2(rojo, ir) - 97.5) < 0.5, lpm

assert calidad_senal(ir[:10 * FS]) > 0.8
assert calidad_senal(60000 + ruido[1][:10 * FS]) < 0.3
assert calidad_senal(np.full(10 * FS, 60000.0)) == 0

alterno = np.where(np.floor(t * 72 / 60) % 2 == 0, 1, 0.5)
fase = t * 72 / 60 % 1
onda = alterno * (np.exp(-((fase - 0.18) / 0.08) ** 2) + 0.5 * np.exp(-((fase - 0.55) / 0.11) ** 2))
assert abs(frecuencia_cardiaca(60000 - 1200 * onda + ruido[1]) - 72) < 2

seno = 60000 + 600 * np.sin(2 * np.pi * 72 / 60 * t) + ruido[1]
assert abs(indice_perfusion(seno) - 2.0) < 0.1

def pulsos(rr):
    latidos = np.cumsum(rr)
    u = t[:, None] - latidos[None, :]
    return 60000 - 1200 * (np.exp(-((u - 0.15) / 0.07) ** 2) + 0.5 * np.exp(-((u - 0.45) / 0.09) ** 2)).sum(axis=1)


t = np.arange(60 * FS) / FS
ruido_largo = np.random.default_rng(2).normal(0, 30, t.size)
metronomo = np.full(80, 0.8)
rmssd, sdnn = variabilidad(pulsos(metronomo) + ruido_largo)
assert rmssd < 5 and sdnn < 5, (rmssd, sdnn)

rr = 0.8 + np.random.default_rng(1).normal(0, 0.04, 80)
rmssd, sdnn = variabilidad(pulsos(rr) + ruido_largo)
verdadero = rr[(np.cumsum(rr) > 1.5) & (np.cumsum(rr) < 58.5)]
rmssd_real = 1000 * np.sqrt(np.mean(np.diff(verdadero) ** 2))
assert abs(rmssd - rmssd_real) < 0.15 * rmssd_real, (rmssd, rmssd_real)
assert abs(sdnn - 1000 * np.std(verdadero, ddof=1)) < 8, (sdnn, 1000 * np.std(verdadero, ddof=1))

assert variabilidad(pulsos(metronomo)[: 10 * FS]) is None

print("OK")
