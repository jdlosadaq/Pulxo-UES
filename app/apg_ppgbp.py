import re
import sys
import warnings
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QApplication
from scipy.signal import butter, detrend, filtfilt, find_peaks, resample_poly
from scipy.stats import pearsonr, spearmanr

FS_ORIGEN = 1000
INDICES = ("b/a", "c/a", "d/a", "e/a", "AGI")
CONFIGURACIONES = ((1000, 15), (100, 8), (100, 12))
GRUPOS = ((0, 40), (40, 60), (60, 200))
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def etiquetas(ruta):
    hoja = zipfile.ZipFile(ruta)
    textos = ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")) for si in ET.fromstring(hoja.read("xl/sharedStrings.xml")).findall("m:si", NS)]
    sujetos = {}
    for fila in ET.fromstring(hoja.read("xl/worksheets/sheet1.xml")).iter(f"{{{NS['m']}}}row"):
        celdas = {}
        for c in fila.findall("m:c", NS):
            v = c.find("m:v", NS)
            if v is not None:
                celdas[re.match(r"[A-Z]+", c.get("r")).group()] = textos[int(v.text)] if c.get("t") == "s" else v.text
        if celdas.get("B", "").isdigit():
            sujetos[int(celdas["B"])] = (int(celdas["D"]), int(celdas["G"]))
    return sujetos


def apg(x, fs, corte):
    x = resample_poly(x, fs, FS_ORIGEN) if fs != FS_ORIGEN else np.asarray(x, dtype=float)
    velocidad = np.gradient(filtfilt(*butter(3, 15, fs=fs), x - x.mean()))
    if velocidad.max() < -velocidad.min():
        x = -x
    suave = filtfilt(*butter(3, corte, fs=fs), detrend(x))
    return np.gradient(np.gradient(suave, 1 / fs), 1 / fs)


def ondas(senal, fs):
    inicio, fin = int(0.2 * fs), senal.size - int(0.6 * fs)
    if fin <= inicio:
        return np.empty((0, 5))
    candidatos = find_peaks(senal, height=0.5 * senal[inicio:fin].max())[0]
    candidatos = candidatos[(candidatos >= inicio) & (candidatos < fin)]
    filas = []
    for k, ia in enumerate(candidatos):
        siguiente = candidatos[k + 1] if k + 1 < candidatos.size else senal.size
        tramo = senal[ia:min(ia + int(0.5 * fs), siguiente)]
        a = senal[ia]
        altos = find_peaks(tramo, prominence=0.05 * a)[0]
        bajos = find_peaks(-tramo, prominence=0.05 * a)[0]
        fila, posicion = [a, np.nan, np.nan, np.nan, np.nan], 0
        for j, fuente in enumerate((bajos, altos, bajos, altos)):
            despues = fuente[fuente > posicion]
            if despues.size == 0:
                break
            posicion = despues[0]
            fila[j + 1] = tramo[posicion]
        filas.append(fila)
    return np.array(filas).reshape(-1, 5)


def indices(onda):
    a, b, c, d, e = onda.T
    return np.column_stack([b / a, c / a, d / a, e / a, (b - c - d - e) / a])


def sujetos_indices(carpeta, fs, corte, edades):
    por_sujeto = {}
    for ruta in sorted((carpeta / "0_subject").glob("*.txt")):
        latidos = indices(ondas(apg(np.loadtxt(ruta), fs, corte), fs))
        por_sujeto.setdefault(int(ruta.stem.split("_")[0]), []).append(latidos)
    filas, completos, total = [], 0, 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for sujeto, registros in por_sujeto.items():
            latidos = np.vstack(registros)
            completos += (~np.isnan(latidos[:, 4])).sum()
            total += len(latidos)
            filas.append((sujeto, *edades[sujeto], *np.nanmean(latidos, axis=0), (~np.isnan(latidos[:, 4])).mean() if len(latidos) else np.nan))
    return np.array(filas), completos, total


def correlacion(x, y):
    validos = ~(np.isnan(x) | np.isnan(y))
    x, y = x[validos], y[validos]
    r = pearsonr(x, y)[0]
    z, error = np.arctanh(r), 1 / np.sqrt(x.size - 3)
    return x.size, r, np.tanh(z - 1.96 * error), np.tanh(z + 1.96 * error), spearmanr(x, y)[0]


def parcial(x, y, z):
    validos = ~(np.isnan(x) | np.isnan(y) | np.isnan(z))
    x, y, z = x[validos], y[validos], z[validos]
    return pearsonr(*(v - np.polyval(np.polyfit(z, v, 1), z) for v in (x, y)))[0]


def graficar(grafica, edad, valor, nombre):
    validos = ~np.isnan(valor)
    grafica.setTitle(f"{nombre} contra la edad")
    grafica.setLabel("bottom", "edad (años)")
    grafica.setLabel("left", nombre)
    grafica.plot(edad[validos], valor[validos], pen=None, symbol="o", symbolSize=5, symbolBrush=(30, 120, 220, 110))
    recta = np.polyfit(edad[validos], valor[validos], 1)
    grafica.plot([edad.min(), edad.max()], np.polyval(recta, [edad.min(), edad.max()]), pen=pg.mkPen("r", width=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit('Usar app/apg_ppgbp.py con la carpeta "Data File" de PPG-BP')

    carpeta = Path(sys.argv[1])
    edades = etiquetas(carpeta / "PPG-BP dataset.xlsx")
    app = QApplication(sys.argv)
    pg.setConfigOptions(background="w", foreground="k", antialias=True)
    lienzo = pg.GraphicsLayoutWidget()
    for columna, (fs, corte) in enumerate(CONFIGURACIONES):
        datos, completos, total = sujetos_indices(carpeta, fs, corte, edades)
        edad, presion = datos[:, 1], datos[:, 2]
        print(f"\n{fs} Hz, pasa-bajos {corte} Hz: {len(datos)} sujetos, {total} latidos, {100 * completos / total:.0f} % con a-e completos")
        print("  detección completa por edad: " + ", ".join(
            f"{lo}-{hi if hi < 200 else '+'} años {100 * np.nanmean(datos[(edad >= lo) & (edad < hi), 8]):.0f} %" for lo, hi in GRUPOS))
        print(f"  {'índice':<7}{'n':>5}{'r(edad)':>9}{'IC 95 %':>16}{'rho':>7}{'r(edad|PAS)':>13}{'r(PAS)':>8}")
        for k, nombre in enumerate(INDICES):
            valor = datos[:, 3 + k]
            n, r, bajo, alto, rho = correlacion(valor, edad)
            print(f"  {nombre:<7}{n:>5}{r:>9.2f}{f'[{bajo:.2f}, {alto:.2f}]':>16}{rho:>7.2f}{parcial(valor, edad, presion):>13.2f}{correlacion(valor, presion)[1]:>8.2f}")
        for fila, k in enumerate((0, 4)):
            graficar(lienzo.addPlot(row=fila, col=columna), edad, datos[:, 3 + k], f"{INDICES[k]} ({fs} Hz, {corte} Hz)")
    lienzo.resize(1500, 800)
    lienzo.show()
    app.processEvents()
    Path("validacion").mkdir(exist_ok=True)
    lienzo.grab().save("validacion/apg_ppgbp.png")
    print("\nGráfico guardado en validacion/apg_ppgbp.png")
