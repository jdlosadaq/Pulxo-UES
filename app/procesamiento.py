import sys

import numpy as np
from scipy.signal import butter, correlate, filtfilt, find_peaks

from lector import FS

A, B = 110, 25
BANDA = (0.5, 4)
CALIDAD_MINIMA = 0.5


def cargar(ruta):
    datos = np.loadtxt(ruta, delimiter=",", skiprows=1)
    return datos[:, 1], datos[:, 2]


def pasabanda(x):
    b, a = butter(2, BANDA, btype="band", fs=FS)
    return filtfilt(b, a, x)


def periodo(ir):
    f = pasabanda(ir)
    ac = correlate(f, f)[f.size - 1:]
    minimo, maximo = int(FS * 60 / 240), int(FS * 60 / 30)
    tramo = ac[minimo:maximo]
    picos, _ = find_peaks(tramo, height=0.5 * tramo.max())
    retardo = minimo + (picos[0] if picos.size else np.argmax(tramo))
    return retardo, ac[retardo] / ac[0] if ac[0] > 1 else 0.0


def frecuencia_cardiaca(ir):
    return 60 * FS / periodo(ir)[0]


def calidad_senal(ir):
    return periodo(ir)[1]


def spo2(rojo, ir):
    r = (np.std(pasabanda(rojo)) / np.mean(rojo)) / (np.std(pasabanda(ir)) / np.mean(ir))
    return A - B * r


def indice_perfusion(ir):
    return 100 * np.ptp(pasabanda(ir)[FS:-FS]) / np.mean(ir)


def variabilidad(ir):
    f = -pasabanda(ir)[FS:-FS]
    picos, _ = find_peaks(f, distance=int(0.6 * FS * 60 / frecuencia_cardiaca(ir)), prominence=np.std(f))
    if picos.size < 32:
        return None
    y0, y1, y2 = f[picos - 1], f[picos], f[picos + 1]
    rr = np.diff((picos + 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)) / FS)
    valido = np.abs(rr / np.median(rr) - 1) < 0.3
    sucesivos = valido[:-1] & valido[1:]
    if sucesivos.sum() < 30:
        return None
    return 1000 * np.sqrt(np.mean(np.diff(rr)[sucesivos] ** 2)), 1000 * np.std(rr[valido], ddof=1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usar app/procesamiento.py con la ruta de un CSV de sesiones/")

    rojo, ir = cargar(sys.argv[1])
    print(f"FC: {frecuencia_cardiaca(ir):.0f} lpm")
    print(f"SpO2: {spo2(rojo, ir):.1f} %")
