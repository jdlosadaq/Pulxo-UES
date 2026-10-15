import csv
import queue
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
import pyqtgraph as pg
import serial
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QStyle, QVBoxLayout, QWidget
from scipy.signal import butter, sosfilt, sosfilt_zi

from lector import BAUDIO, FS, muestras, simulador
from procesamiento import frecuencia_cardiaca, indice_perfusion, spo2

VENTANA = 10 * FS
TENDENCIA = 60
DEDO_MINIMO = 50000
SOS = np.vstack([butter(1, 0.5, btype="high", fs=FS, output="sos"), butter(2, 8, fs=FS, output="sos")])

AZUL, ROJO, VERDE = "#4f8fe6", "#e5534b", "#57ab5a"
ESTILO = """
QWidget { background: #1e1f22; color: #d0d0d0; font-size: 14px; }
QFrame#tarjeta { background: #2b2d31; border-radius: 6px; }
QFrame#tarjeta QLabel { background: transparent; }
QPushButton { background: #2b2d31; border: 1px solid #444; border-radius: 4px; padding: 6px 14px; }
QPushButton:hover { background: #3a3d42; }
"""

pg.setConfigOptions(background="#1e1f22", foreground="#d0d0d0", antialias=True)


def grafica(titulo, unidad, color):
    g = pg.PlotWidget(title=titulo)
    g.setLabel("bottom", "tiempo", "s")
    g.setLabel("left", unidad)
    g.showGrid(x=True, y=True, alpha=0.2)
    return g, g.plot(pen=pg.mkPen(color, width=2))


def tarjeta(titulo, color):
    caja = QFrame(objectName="tarjeta")
    valor = QLabel("--", styleSheet=f"font-size: 48px; font-weight: bold; color: {color};")
    columna = QVBoxLayout(caja)
    columna.addWidget(QLabel(titulo))
    columna.addWidget(valor)
    return caja, valor


class Panel(QWidget):
    def __init__(self, fuente, origen):
        super().__init__(windowTitle="Pulxo-UES", styleSheet=ESTILO)
        self.origen = origen
        self.cola = queue.Queue()
        self.rojo, self.ir, self.vista = deque(maxlen=VENTANA), deque(maxlen=VENTANA), deque(maxlen=VENTANA)
        self.fc, self.sat = deque(maxlen=TENDENCIA), deque(maxlen=TENDENCIA)
        self.archivo = self.escritor = self.filtro = None

        self.hora, self.estado = QLabel(), QLabel()
        icono = self.style().standardIcon
        self.boton = QPushButton(icono(QStyle.StandardPixmap.SP_DialogSaveButton), "Grabar", clicked=self.grabar)
        salir = QPushButton("Salir", clicked=self.close)
        barra = QHBoxLayout()
        barra.addWidget(self.hora)
        barra.addWidget(self.estado)
        barra.addStretch()
        barra.addWidget(QLabel("PULXO-UES · PULSIOXÍMETRO MAX30102", styleSheet="font-size: 16px; font-weight: bold;"))
        barra.addStretch()
        barra.addWidget(self.boton)
        barra.addWidget(salir)

        graf_pleth, self.curva = grafica("Pletismograma (infrarrojo)", "", AZUL)
        graf_pleth.hideAxis("left")
        caja_fc, self.valor_fc = tarjeta("Frecuencia cardiaca (lpm)", AZUL)
        caja_sat, self.valor_sat = tarjeta("SpO₂ (%) · sin calibrar", VERDE)
        caja_pi, self.valor_pi = tarjeta("Índice de perfusión (%)", "#d0d0d0")
        graf_fc, self.curva_fc = grafica("Frecuencia cardiaca", "lpm", AZUL)
        graf_sat, self.curva_sat = grafica("SpO₂", "%", VERDE)
        graf_fc.setYRange(40, 160)
        graf_sat.setYRange(80, 100)

        tendencias = QHBoxLayout()
        tendencias.addWidget(graf_fc)
        tendencias.addWidget(graf_sat)
        izquierda, derecha = QVBoxLayout(), QVBoxLayout()
        izquierda.addWidget(graf_pleth, 2)
        izquierda.addLayout(tendencias, 1)
        for elemento in (caja_fc, caja_sat, caja_pi):
            derecha.addWidget(elemento)
        cuerpo = QHBoxLayout()
        cuerpo.addLayout(izquierda, 3)
        cuerpo.addLayout(derecha, 1)
        principal = QVBoxLayout(self)
        principal.addLayout(barra)
        principal.addLayout(cuerpo)

        self.hilo = threading.Thread(target=self.leer, args=(fuente,), daemon=True)
        self.hilo.start()
        for intervalo, funcion in ((50, self.refrescar), (1000, self.calcular)):
            reloj = QTimer(self)
            reloj.timeout.connect(funcion)
            reloj.start(intervalo)

    def leer(self, fuente):
        for m in muestras(fuente):
            self.cola.put(m)

    def refrescar(self):
        nuevas = []
        while not self.cola.empty():
            nuevas.append(self.cola.get())
        if not nuevas:
            return
        if self.escritor:
            self.escritor.writerows(nuevas)
        datos = np.array(nuevas, dtype=float)
        if self.filtro is None:
            self.filtro = sosfilt_zi(SOS) * datos[0, 2]
        filtrado, self.filtro = sosfilt(SOS, datos[:, 2], zi=self.filtro)
        self.rojo.extend(datos[:, 1])
        self.ir.extend(datos[:, 2])
        self.vista.extend(-filtrado)
        t = np.arange(-len(self.vista), 0) / FS
        self.curva.setData(t, np.array(self.vista))

    def calcular(self):
        self.hora.setText(f"{datetime.now():%H:%M:%S}")
        rojo, ir = np.array(self.rojo), np.array(self.ir)
        if not self.hilo.is_alive():
            estado = "Desconectado"
        elif len(ir) < VENTANA:
            estado = "Llenando ventana"
        elif ir.min() < DEDO_MINIMO:
            estado = "Sin dedo"
        else:
            estado = "Midiendo"
        grabando = f" · <span style='color: {ROJO};'>● GRABANDO</span>" if self.archivo else ""
        self.estado.setText(f"{self.origen} · {estado}{grabando}")

        if estado != "Midiendo":
            for valor in (self.valor_fc, self.valor_sat, self.valor_pi):
                valor.setText("--")
            return
        self.fc.append(frecuencia_cardiaca(ir))
        self.sat.append(spo2(rojo, ir))
        self.valor_fc.setText(f"{self.fc[-1]:.0f}")
        self.valor_sat.setText(f"{self.sat[-1]:.0f}")
        self.valor_pi.setText(f"{indice_perfusion(ir):.1f}")
        segundos = np.arange(-len(self.fc) + 1, 1)
        self.curva_fc.setData(segundos, list(self.fc))
        self.curva_sat.setData(segundos, list(self.sat))

    def grabar(self):
        if self.archivo:
            self.archivo.close()
            self.archivo = self.escritor = None
            self.boton.setText("Grabar")
            return
        Path("sesiones").mkdir(exist_ok=True)
        ruta = Path("sesiones") / f"sesion_{datetime.now():%Y%m%d_%H%M%S}.csv"
        self.archivo = open(ruta, "w", newline="")
        self.escritor = csv.writer(self.archivo)
        self.escritor.writerow(["n", "rojo", "ir"])
        self.boton.setText("Detener")

    def closeEvent(self, evento):
        if self.archivo:
            self.archivo.close()
        super().closeEvent(evento)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usar app/interfaz.py con el COM 3 o con el simulador")

    if sys.argv[1] == "simulador":
        fuente, origen = simulador(), "Simulador"
    else:
        puerto = serial.Serial(sys.argv[1], BAUDIO, timeout=1)
        fuente, origen = iter(puerto.readline, None), f"Arduino ({sys.argv[1]})"

    app = QApplication(sys.argv)
    panel = Panel(fuente, origen)
    panel.resize(1280, 720)
    panel.show()
    sys.exit(app.exec())
