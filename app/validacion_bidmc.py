import re
import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from scipy.signal import butter, filtfilt, find_peaks, resample_poly

from lector import FS
from procesamiento import frecuencia_cardiaca, variabilidad

SEGUNDOS_FC = 10
SEGUNDOS_HRV = 60
MEDIDAS = ("FC (lpm)", "RMSSD (ms)", "SDNN (ms)")


def leer_registro(base):
    lineas = Path(f"{base}.hea").read_text().splitlines()
    fs = int(lineas[0].split()[2])
    canales = [linea.split() for linea in lineas[1:] if not linea.startswith("#")]
    assert all(c[1] == "16" for c in canales), "solo formato 16"
    crudo = np.fromfile(f"{base}.dat", dtype="<i2").reshape(-1, len(canales))
    senales = {}
    for k, canal in enumerate(canales):
        ganancia, cero = re.match(r"([\d.]+)\((-?\d+)\)", canal[2]).groups()
        senales[canal[-1].strip(",")] = (crudo[:, k] - float(cero)) / float(ganancia)
    return fs, senales


def latidos_ecg(ecg, fs):
    b, a = butter(2, (5, 25), btype="band", fs=fs)
    x = filtfilt(b, a, ecg)
    ancho = int(0.1 * fs)
    energia = np.convolve(x ** 2, np.ones(ancho) / ancho, mode="same")
    picos, _ = find_peaks(energia, distance=int(0.3 * fs), height=0.2 * np.percentile(energia, 99))
    medio = int(0.05 * fs)
    afinados = [max(p - medio, 0) + np.argmax(np.abs(x[max(p - medio, 0):p + medio])) for p in picos]
    return np.array(afinados) / fs


def fc_referencia(latidos):
    if latidos.size < 3:
        return None
    return 60 * (latidos.size - 1) / (latidos[-1] - latidos[0])


def vfc_referencia(latidos):
    if latidos.size < 3:
        return None
    rr = np.diff(latidos)
    valido = np.abs(rr / np.median(rr) - 1) < 0.3
    sucesivos = valido[:-1] & valido[1:]
    if sucesivos.sum() < 30:
        return None
    return 1000 * np.sqrt(np.mean(np.diff(rr)[sucesivos] ** 2)), 1000 * np.std(rr[valido], ddof=1)


def evaluar(base):
    fs, senales = leer_registro(base)
    ppg = resample_poly(-senales["PLETH"], FS, fs)
    latidos = latidos_ecg(senales["II"], fs)
    pares = {medida: [] for medida in MEDIDAS}
    for t0 in range(0, ppg.size // FS - SEGUNDOS_FC + 1, SEGUNDOS_FC):
        referencia = fc_referencia(latidos[(latidos >= t0) & (latidos < t0 + SEGUNDOS_FC)])
        if referencia is not None:
            medida = frecuencia_cardiaca(ppg[t0 * FS:(t0 + SEGUNDOS_FC) * FS])
            pares["FC (lpm)"].append((referencia, medida))
    for t0 in range(0, ppg.size // FS - SEGUNDOS_HRV + 1, SEGUNDOS_HRV):
        referencia = vfc_referencia(latidos[(latidos >= t0 + 1) & (latidos < t0 + SEGUNDOS_HRV - 1)])
        if referencia is not None:
            medida = variabilidad(ppg[t0 * FS:(t0 + SEGUNDOS_HRV) * FS]) or (None, None)
            for nombre, r, m in zip(MEDIDAS[1:], referencia, medida):
                pares[nombre].append((r, m))
    return pares


def estadisticas(pares):
    validos = np.array([p for p in pares if p[1] is not None], dtype=float)
    referencia, medida = validos.T
    diferencia = medida - referencia
    return {
        "n": len(validos),
        "descartadas": len(pares) - len(validos),
        "sesgo": diferencia.mean(),
        "limite": 1.96 * diferencia.std(ddof=1),
        "mae": np.abs(diferencia).mean(),
        "rmse": np.sqrt(np.mean(diferencia ** 2)),
        "r": np.corrcoef(referencia, medida)[0, 1],
    }


def bland_altman(grafica, pares, estadistica, nombre):
    validos = np.array([p for p in pares if p[1] is not None], dtype=float)
    referencia, medida = validos.T
    grafica.setTitle(nombre)
    grafica.setLabel("bottom", "media de ECG y PPG")
    grafica.setLabel("left", "PPG − ECG")
    grafica.plot((referencia + medida) / 2, medida - referencia, pen=None, symbol="o", symbolSize=5, symbolBrush=(30, 120, 220, 110))
    grafica.addLine(y=estadistica["sesgo"], pen=pg.mkPen("r"))
    for y in (estadistica["sesgo"] + estadistica["limite"], estadistica["sesgo"] - estadistica["limite"]):
        grafica.addLine(y=y, pen=pg.mkPen("r", style=Qt.PenStyle.DashLine))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usar app/validacion_bidmc.py con la carpeta de los registros BIDMC (datos/bidmc)")

    registros = sorted(Path(sys.argv[1]).glob("bidmc*.hea"))
    if not registros:
        sys.exit("No hay archivos bidmc*.hea en esa carpeta")

    pares = {medida: [] for medida in MEDIDAS}
    for hea in registros:
        for medida, p in evaluar(hea.with_suffix("")).items():
            pares[medida] += p

    resultados = {medida: estadisticas(p) for medida, p in pares.items()}
    print(f"{len(registros)} registros de BIDMC")
    print(f"{'medida':<12}{'n':>5}{'descart.':>9}{'sesgo':>9}{'±1.96·DE':>10}{'MAE':>8}{'RMSE':>8}{'r':>7}")
    for medida, e in resultados.items():
        print(f"{medida:<12}{e['n']:>5}{e['descartadas']:>9}{e['sesgo']:>9.2f}{e['limite']:>10.2f}{e['mae']:>8.2f}{e['rmse']:>8.2f}{e['r']:>7.2f}")

    app = QApplication(sys.argv)
    pg.setConfigOptions(background="w", foreground="k", antialias=True)
    lienzo = pg.GraphicsLayoutWidget()
    for medida in MEDIDAS:
        bland_altman(lienzo.addPlot(), pares[medida], resultados[medida], f"Bland-Altman: {medida}")
    lienzo.resize(1500, 480)
    lienzo.show()
    app.processEvents()
    Path("validacion").mkdir(exist_ok=True)
    lienzo.grab().save("validacion/bidmc_bland_altman.png")
    print("Gráfico guardado en validacion/bidmc_bland_altman.png")
