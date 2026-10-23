import tempfile
from pathlib import Path

import numpy as np

from validacion_bidmc import estadisticas, evaluar, latidos_ecg, leer_registro

FS_ORIGEN = 125
t = np.arange(120 * FS_ORIGEN) / FS_ORIGEN
rr = 0.8 + np.random.default_rng(1).normal(0, 0.04, 200)
latidos = np.cumsum(rr)
latidos = latidos[latidos < 120]
u = t[:, None] - latidos[None, :]
ppg = 1 + (np.exp(-((u - 0.15) / 0.07) ** 2) + 0.5 * np.exp(-((u - 0.45) / 0.09) ** 2)).sum(axis=1)
ecg = np.exp(-((u / 0.01) ** 2)).sum(axis=1)

base = Path(tempfile.mkdtemp()) / "registro"
Path(f"{base}.hea").write_text(
    f"registro 2 {FS_ORIGEN} {t.size}\n"
    "registro.dat 16 1000(-500)/NU 0 0 0 0 0 PLETH,\n"
    "registro.dat 16 200(100)/mV 0 0 0 0 0 II,\n"
    "# <age>: 88\n"
)
np.column_stack([np.round(ppg * 1000 - 500), np.round(ecg * 200 + 100)]).astype("<i2").tofile(f"{base}.dat")

fs, senales = leer_registro(base)
assert fs == FS_ORIGEN and set(senales) == {"PLETH", "II"}
assert np.abs(senales["PLETH"] - ppg).max() < 0.001
assert np.abs(senales["II"] - ecg).max() < 0.01

detectados = latidos_ecg(senales["II"], fs)
assert abs(detectados.size - latidos.size) <= 1, (detectados.size, latidos.size)
assert all(np.abs(latidos - d).min() < 0.02 for d in detectados)

pares = evaluar(base)
assert len(pares["FC (lpm)"]) == 12 and len(pares["RMSSD (ms)"]) == 2 and len(pares["SDNN (ms)"]) == 2
assert all(abs(r - m) < 2 for r, m in pares["FC (lpm)"]), pares["FC (lpm)"]
for medida in ("RMSSD (ms)", "SDNN (ms)"):
    assert all(abs(r - m) < 0.2 * r for r, m in pares[medida]), pares[medida]

e = estadisticas([(1, 2), (2, 3), (3, 4), (4, 5), (5, None)])
assert e["n"] == 4 and e["descartadas"] == 1
assert e["sesgo"] == 1 and e["limite"] == 0 and e["mae"] == 1 and e["rmse"] == 1 and abs(e["r"] - 1) < 1e-9

print("OK")
