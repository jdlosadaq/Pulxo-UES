import csv
import os
import tempfile
import threading
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

from interfaz import VENTANA, Panel
from lector import FS

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.chdir(tempfile.mkdtemp())
app = QApplication([])
panel = Panel(iter(threading.Event().wait, None), "Prueba")


def alimentar(rojo, ir):
    for n in range(VENTANA):
        panel.cola.put((n, int(rojo[n]), int(ir[n])))
    panel.refrescar()
    panel.calcular()


panel.calcular()
assert panel.valor_fc.text() == "--"

pulso = np.sin(2 * np.pi * 72 / 60 * np.arange(VENTANA) / FS)
panel.grabar()
alimentar(50000 + 500 * pulso, 60000 + 1200 * pulso)
panel.grabar()
assert abs(int(panel.valor_fc.text()) - 72) <= 2, panel.valor_fc.text()
assert abs(float(panel.valor_sat.text()) - 97.5) <= 1, panel.valor_sat.text()
assert abs(float(panel.valor_pi.text()) - 4.0) < 0.2, panel.valor_pi.text()
assert "Midiendo" in panel.estado.text(), panel.estado.text()

with open(next(Path("sesiones").glob("*.csv")), newline="") as archivo:
    filas = list(csv.reader(archivo))
assert filas[0] == ["n", "rojo", "ir"]
assert len(filas) == VENTANA + 1

alimentar(np.full(VENTANA, 500), np.full(VENTANA, 600))
assert panel.valor_fc.text() == "--"
assert "Sin dedo" in panel.estado.text(), panel.estado.text()

print("OK")
