from itertools import islice

import numpy as np
from scipy.signal import find_peaks

import lector
from lector import FS, muestras, onda_pulso, parsear
from procesamiento import frecuencia_cardiaca, indice_perfusion, spo2

assert parsear(b"5,51234,60876\r\n") == (5, 51234, 60876)
assert parsear(b"# Pulxo-UES fs=100\r\n") is None
assert parsear(b"# n,rojo,ir\r\n") is None
assert parsear(b"12,345\r\n") is None
assert parsear(b"\xff\xfe1,2,3\r\n") is None
assert parsear(b"") is None

lineas = [b"# n,rojo,ir\r\n", b"0,10,20\r\n", b"1,11,21\r\n", b"basura\r\n", b"3,13,23\r\n"]
assert list(muestras(lineas)) == [(0, 10, 20), (1, 11, 21), (3, 13, 23)]

fases = np.linspace(0, 1, 1000, endpoint=False)
onda = np.array([onda_pulso(f) for f in fases])
assert abs(fases[onda.argmax()] - 0.18) < 0.01
picos, _ = find_peaks(onda)
assert len(picos) == 2 and abs(fases[picos[1]] - 0.55) < 0.02, fases[picos]
assert abs(onda.mean()) < 0.01

lector.time.sleep = lambda s: None
datos = np.array([m for m in muestras(islice(lector.simulador(), 30 * FS))], dtype=float)
rojo, ir = datos[:, 1], datos[:, 2]
assert abs(frecuencia_cardiaca(ir) - 72) < 2
assert abs(spo2(rojo, ir) - 97.5) < 0.5
assert 2.5 < indice_perfusion(ir) < 4.5
assert ir[15] < ir.mean() - 1000

print("OK")
