import numpy as np

from lector import FS
from procesamiento import (
    amplitudes, calidad_senal, frecuencia_cardiaca, indice_perfusion, indices, latido_promedio, morfologia, ondas,
    segunda_derivada, spo2, suavizar, variabilidad,
)

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

corto = np.arange(int(2.1 * FS)) / FS


def onda_apg(amplitudes_onda, inicio=0.6):
    senal = np.zeros(corto.size)
    for k, amplitud in enumerate(amplitudes_onda):
        senal += amplitud * np.exp(-((corto - inicio - 0.1 * k) / 0.03) ** 2)
    return np.cumsum(np.cumsum(senal)) / FS ** 2


completa = onda_apg((1, -0.6, 0.15, -0.3, 0.1))
posiciones = ondas(completa)
assert posiciones.shape == (1, 5) and np.allclose(posiciones[0], (60, 70, 80, 90, 100), atol=1), posiciones
encontradas = amplitudes(segunda_derivada(completa), posiciones)
assert np.allclose(encontradas[0] / encontradas[0, 0], (1, -0.6, 0.15, -0.3, 0.1), atol=0.05), encontradas
ba, ca, da, ea, agi = indices(encontradas)[0]
assert abs(ba + 0.6) < 0.06 and abs(agi + 0.55) < 0.1, (ba, agi)

solo_ab = onda_apg((1, -0.5))
incompleta = amplitudes(segunda_derivada(solo_ab), ondas(solo_ab))
assert np.isnan(incompleta[0, 2:]).all() and not np.isnan(incompleta[0, :2]).any()
assert np.isnan(indices(incompleta)[0, 4]) and abs(indices(incompleta)[0, 0] + 0.5) < 0.06
assert ondas(np.zeros(corto.size)).shape == (0, 5)
assert ondas(np.zeros(20)).shape == (0, 5)

diez = np.arange(10 * FS) / FS
fase = diez * 72 / 60 % 1
pulso = 60000 - 1200 * (np.exp(-((fase - 0.18) / 0.08) ** 2) + 0.5 * np.exp(-((fase - 0.55) / 0.11) ** 2))
suave = suavizar(-pulso)
assert suave.shape == segunda_derivada(suave).shape == pulso.shape
latidos = ondas(suave)
assert np.allclose(np.diff(latidos[:, 0]), FS * 60 / 72, atol=2), latidos[:, 0]
promedio = latido_promedio(suave, latidos[:, 0], 25, 75)
assert promedio.shape == (100,) and np.argmax(segunda_derivada(promedio)[15:35]) == 10
assert latido_promedio(suave, np.array([5.0]), 25, 75) is None

pulso_medio, segunda_media, marcas, valores, cantidad = morfologia(suave)
assert pulso_medio.shape == segunda_media.shape == (100,) and marcas[0] == 25 and cantidad == len(latidos)
assert valores.shape == (5,) and np.isfinite(valores[:2]).all()
assert morfologia(suave[:50]) is None

estables = []
for semilla in range(6):
    ruidoso = pulso + np.random.default_rng(semilla).normal(0, 15, pulso.size)
    estables.append(morfologia(suavizar(-ruidoso))[3])
estables = np.array(estables)
assert np.ptp(estables[:, 0]) < 0.2 and np.ptp(estables[:, 1]) < 0.1, estables[:, :2]

print("OK")
