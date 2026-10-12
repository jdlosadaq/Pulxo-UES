import csv
import math
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import serial

BAUDIO = 115200
FS = 100


def parsear(linea):
    try:
        n, rojo, ir = (int(x) for x in linea.decode("ascii").strip().split(","))
    except (UnicodeDecodeError, ValueError):
        return None
    return n, rojo, ir


def muestras(lineas):
    anterior = None
    for linea in lineas:
        m = parsear(linea)
        if m is None:
            continue
        if anterior is not None and m[0] != anterior + 1:
            print(f"Aviso: salto en n de {anterior} a {m[0]}", file=sys.stderr)
        anterior = m[0]
        yield m


def simulador(fc=72):
    n = 0
    inicio = time.perf_counter()
    while True:
        pulso = math.sin(2 * math.pi * fc / 60 * n / FS)
        rojo = 50000 + 500 * pulso + random.gauss(0, 30)
        ir = 60000 + 1200 * pulso + random.gauss(0, 30)
        yield f"{n},{int(rojo)},{int(ir)}\r\n".encode()
        n += 1
        espera = inicio + n / FS - time.perf_counter()
        if espera > 0:
            time.sleep(espera)


def grabar(lineas, ruta):
    total = 0
    with open(ruta, "w", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(["n", "rojo", "ir"])
        try:
            for m in muestras(lineas):
                escritor.writerow(m)
                total += 1
        except KeyboardInterrupt:
            pass
    return total


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usar app/lector.py con el COM 3 o con el simulador")

    if sys.argv[1] == "simulador":
        fuente = simulador()
    else:
        puerto = serial.Serial(sys.argv[1], BAUDIO, timeout=1)
        fuente = iter(puerto.readline, None)

    Path("sesiones").mkdir(exist_ok=True)
    ruta = Path("sesiones") / f"sesion_{datetime.now():%Y%m%d_%H%M%S}.csv"
    print(f"Grabando {ruta}. Pulsa Ctrl + C para terminar. ")
    total = grabar(fuente, ruta)
    print(f"{total} muestras ({total / FS:.1f} s) guardadas en {ruta}")
