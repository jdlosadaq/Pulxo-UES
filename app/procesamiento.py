import sys

import numpy as np
from scipy.signal import butter, correlate, filtfilt

from lector import FS

A, B = 110, 25


def cargar(ruta):
    datos = np.loadtxt(ruta, delimiter=",", skiprows=1)
    return datos[:, 1], datos[:, 2]


def pasabanda(x):
    b, a = butter(2, [0.5, 4], btype="band", fs=FS)
    return filtfilt(b, a, x)


def frecuencia_cardiaca(ir):
    f = pasabanda(ir)
    ac = correlate(f, f)[f.size - 1:]
    minimo, maximo = int(FS * 60 / 240), int(FS * 60 / 30)
    return 60 * FS / (minimo + np.argmax(ac[minimo:maximo]))


def spo2(rojo, ir):
    r = (np.std(pasabanda(rojo)) / np.mean(rojo)) / (np.std(pasabanda(ir)) / np.mean(ir))
    return A - B * r


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usar app/procesamiento.py con la ruta de un CSV de sesiones/")

    rojo, ir = cargar(sys.argv[1])
    print(f"FC: {frecuencia_cardiaca(ir):.0f} lpm")
    print(f"SpO2: {spo2(rojo, ir):.1f} %")
