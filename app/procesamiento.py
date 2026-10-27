import sys

import numpy as np
from scipy.signal import butter, correlate, detrend, filtfilt, find_peaks

from lector import FS

A, B = 110, 25
BANDA = (0.5, 4)
CALIDAD_MINIMA = 0.5
CORTE_APG = 12


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


def suavizar(x, fs=FS, corte=CORTE_APG):
    return filtfilt(*butter(3, corte, fs=fs), detrend(x))


def segunda_derivada(suave, fs=FS):
    return np.gradient(np.gradient(suave, 1 / fs), 1 / fs)


def ondas(suave, fs=FS):
    inicio, fin = int(0.2 * fs), suave.size - int(0.6 * fs)
    if fin <= inicio:
        return np.empty((0, 5))
    velocidad = np.gradient(suave, 1 / fs)
    senal = segunda_derivada(suave, fs)
    subidas = find_peaks(velocidad, height=0.5 * velocidad[inicio:fin].max(), distance=int(0.35 * fs))[0]
    subidas = subidas[(subidas >= inicio) & (subidas < fin)]
    filas = []
    for k, v in enumerate(subidas):
        desde = max(v - int(0.12 * fs), 0)
        ia = desde + np.argmax(senal[desde:v + 1])
        siguiente = subidas[k + 1] - int(0.12 * fs) if k + 1 < subidas.size else senal.size
        tramo = senal[ia:min(ia + int(0.5 * fs), siguiente)]
        altos = find_peaks(tramo, prominence=0.05 * tramo[0])[0]
        bajos = find_peaks(-tramo, prominence=0.05 * tramo[0])[0]
        fila, posicion = [ia, np.nan, np.nan, np.nan, np.nan], 0
        for j, fuente in enumerate((bajos, altos, bajos, altos)):
            despues = fuente[fuente > posicion]
            if despues.size == 0:
                break
            posicion = despues[0]
            fila[j + 1] = ia + posicion
        filas.append(fila)
    return np.array(filas, dtype=float).reshape(-1, 5)


def amplitudes(senal, posiciones):
    validas = ~np.isnan(posiciones)
    resultado = np.full(posiciones.shape, np.nan)
    resultado[validas] = senal[posiciones[validas].astype(int)]
    return resultado


def indices(onda):
    a, b, c, d, e = onda.T
    return np.column_stack([b / a, c / a, d / a, e / a, (b - c - d - e) / a])


def latido_promedio(senal, inicios, antes, despues):
    tramos = [senal[int(p) - antes:int(p) + despues] for p in inicios if antes <= p and p + despues <= senal.size]
    return np.mean(tramos, axis=0) if tramos else None


def morfologia(suave, fs=FS):
    posiciones = ondas(suave, fs)
    pulso = latido_promedio(suave, posiciones[:, 0], int(0.25 * fs), int(0.75 * fs))
    if pulso is None:
        return None
    marcas = ondas(pulso, fs)[:1]
    if marcas.size == 0:
        return None
    segunda = segunda_derivada(pulso, fs)
    return pulso, segunda, marcas[0], indices(amplitudes(segunda, marcas))[0], len(posiciones)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usar app/procesamiento.py con la ruta de un CSV de sesiones/")

    rojo, ir = cargar(sys.argv[1])
    print(f"FC: {frecuencia_cardiaca(ir):.0f} lpm")
    print(f"SpO2: {spo2(rojo, ir):.1f} %")
