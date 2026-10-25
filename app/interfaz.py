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
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QStyle, QToolButton, QVBoxLayout, QWidget,
)
from scipy.signal import butter, sosfilt, sosfilt_zi

from lector import BAUDIO, FS, muestras, simulador
from procesamiento import CALIDAD_MINIMA, calidad_senal, frecuencia_cardiaca, indice_perfusion, spo2, variabilidad

VENTANA = 10 * FS
VENTANA_HRV = 60 * FS
TENDENCIA = 60
DEDO_MINIMO = 50000
LIMITES_FC = (50, 120)
SPO2_MINIMA = 90
SOS = np.vstack([butter(1, 0.5, btype="high", fs=FS, output="sos"), butter(2, 8, fs=FS, output="sos")])

AZUL, ROJO, VERDE = "#f74040", "#e5534b", "#34ff37"
ZONA = (210, 153, 34, 45)
APAGADO = "#4a2a2d"
COLORES_ZONA = ("#d29922", VERDE, "#4aa3ff")
ETIQUETAS = ("Bajo", "Típico", "Alto")
HRV = {
    "RMSSD": (
        "Cambio de un latido al siguiente. Mide el freno vagal: descanso y recuperación.",
        (19, 75),
        (
            "Poca modulación vagal: estrés, cansancio o mala recuperación.",
            "Modulación vagal habitual en reposo.",
            "Mucha modulación vagal: descanso o buena condición. El ruido en la señal también la sube.",
        ),
    ),
    "SDNN": (
        "Dispersión de todos los intervalos entre latidos. Mide la variabilidad total.",
        (32, 93),
        (
            "Poca variabilidad total: regulación autonómica limitada, estrés o fatiga.",
            "Variabilidad total habitual en reposo.",
            "Variabilidad total alta: buena adaptabilidad. Descarta que sea ruido o movimiento.",
        ),
    ),
}
ESTILO = """
QWidget { background: #1e1f22; color: #d0d0d0; font-size: 14px; }
QFrame#tarjeta { background: #2b2d31; border-radius: 6px; }
QFrame#tarjeta QLabel { background: transparent; }
QPushButton { background: #2b2d31; border: 1px solid #444; border-radius: 4px; padding: 6px 14px; }
QPushButton:hover { background: #3a3d42; }
QCheckBox:disabled { color: #6e6e6e; }
QToolButton { background: transparent; border: none; font-weight: bold; }
"""

pg.setConfigOptions(background="#1e1f22", foreground="#d0d0d0", antialias=True)


def grafica(titulo, unidad, color, ancho):
    g = pg.PlotWidget(title=titulo)
    g.setXRange(0, ancho, padding=0)
    g.setLabel("bottom", "tiempo", "s")
    g.getAxis("bottom").enableAutoSIPrefix(False)
    g.setLabel("left", unidad)
    g.showGrid(x=True, y=True, alpha=0.2)
    return g, g.plot(pen=pg.mkPen(color, width=2))


def avanzar(grafica, inicio, ultimo, ancho):
    fin = max(ultimo, inicio + ancho)
    grafica.setXRange(fin - ancho, fin, padding=0)


def zona(grafica, limites):
    region = pg.LinearRegionItem(limites, orientation="horizontal", brush=ZONA, pen=(0, 0, 0, 0), movable=False)
    region.setZValue(-10)
    grafica.addItem(region)
    return region


def estilo_numero(color):
    return f"font-size: 96px; font-weight: bold; color: {color};"


def tarjeta(titulo, color, sufijo=""):
    caja = QFrame(objectName="tarjeta")
    valor = QLabel("--", styleSheet=estilo_numero(color))
    unidad = QLabel(sufijo, styleSheet=estilo_numero(color))
    unidad.setVisible(bool(sufijo))
    fila = QHBoxLayout()
    fila.addStretch()
    fila.addWidget(valor)
    fila.addWidget(unidad)
    fila.addStretch()
    columna = QVBoxLayout(caja)
    columna.addWidget(QLabel(titulo, alignment=Qt.AlignmentFlag.AlignCenter))
    columna.addLayout(fila)
    return caja, valor, unidad


def zona_hrv(valor, cortes):
    return sum(valor >= corte for corte in cortes)


def estilo_zona(color, activa):
    if activa:
        return f"background: {color}; color: #000000; font-weight: bold; border-radius: 4px; padding: 4px;"
    return "background: transparent; color: #6e6e6e; border: 1px solid #444; border-radius: 4px; padding: 4px;"


def bloque(nombre):
    descripcion, cortes, _ = HRV[nombre]
    rangos = (f"< {cortes[0]}", f"{cortes[0]}–{cortes[1]}", f"> {cortes[1]}")
    caja = QFrame(objectName="tarjeta")
    valor = QLabel("--", styleSheet="font-size: 40px; font-weight: bold;")
    escala = [QLabel(f"{e}\n{r} ms", alignment=Qt.AlignmentFlag.AlignCenter) for e, r in zip(ETIQUETAS, rangos)]
    interpretacion = QLabel(wordWrap=True)
    cabecera, niveles = QHBoxLayout(), QHBoxLayout()
    cabecera.addWidget(QLabel(nombre, styleSheet="font-size: 16px; font-weight: bold;"))
    cabecera.addStretch()
    cabecera.addWidget(valor)
    cabecera.addWidget(QLabel("ms"))
    for etiqueta in escala:
        niveles.addWidget(etiqueta)
    columna = QVBoxLayout(caja)
    columna.addLayout(cabecera)
    columna.addWidget(QLabel(descripcion, wordWrap=True))
    columna.addLayout(niveles)
    columna.addWidget(interpretacion)
    return caja, valor, escala, interpretacion


class Ajustes(QDialog):
    def __init__(self, padre, limites_fc, spo2_minima):
        super().__init__(padre, windowTitle="Ajustes")
        self.fc_min = QSpinBox(minimum=30, maximum=239)
        self.fc_max = QSpinBox(minimum=31, maximum=240)
        self.spo2_min = QSpinBox(minimum=70, maximum=99, value=int(spo2_minima))
        self.fc_min.valueChanged.connect(lambda v: self.fc_max.setMinimum(v + 1))
        self.fc_max.valueChanged.connect(lambda v: self.fc_min.setMaximum(v - 1))
        self.fc_max.setValue(int(limites_fc[1]))
        self.fc_min.setValue(int(limites_fc[0]))
        self.alarma = QCheckBox("Alarma al salir de los límites (en construcción)", enabled=False)
        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            accepted=self.accept,
            rejected=self.reject,
        )
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("Aceptar")
        botones.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        formulario = QFormLayout(self)
        formulario.addRow("FC mínima (lpm)", self.fc_min)
        formulario.addRow("FC máxima (lpm)", self.fc_max)
        formulario.addRow("SpO₂ mínima (%)", self.spo2_min)
        formulario.addRow(self.alarma)
        formulario.addRow(QLabel("Los límites son una referencia visual. La SpO₂ no está calibrada."))
        formulario.addRow(botones)


class Panel(QWidget):
    def __init__(self, fuente, origen):
        super().__init__(windowTitle="Pulxo-UES", styleSheet=ESTILO)
        self.origen = origen
        self.cola = queue.Queue()
        self.rojo, self.ir, self.vista = deque(maxlen=VENTANA), deque(maxlen=VENTANA), deque(maxlen=VENTANA)
        self.fc, self.sat = deque(maxlen=TENDENCIA), deque(maxlen=TENDENCIA)
        self.ir_hrv = deque(maxlen=VENTANA_HRV)
        self.tiempo, self.tiempo_tendencia = deque(maxlen=VENTANA), deque(maxlen=TENDENCIA)
        self.archivo = self.escritor = self.filtro = None
        self.midiendo, self.ultimo_latido = False, -np.inf

        self.hora, self.estado = QLabel(), QLabel()
        icono = self.style().standardIcon
        self.boton = QPushButton(icono(QStyle.StandardPixmap.SP_DialogSaveButton), "Grabar", clicked=self.grabar)
        ajustes = QPushButton("Ajustes", clicked=self.configurar)
        salir = QPushButton("Salir", clicked=self.close)
        barra = QHBoxLayout()
        barra.addWidget(self.hora)
        barra.addWidget(self.estado)
        barra.addStretch()
        barra.addWidget(QLabel("PULXO-UES · PULSIOXÍMETRO MAX30102", styleSheet="font-size: 16px; font-weight: bold;"))
        barra.addStretch()
        barra.addWidget(ajustes)
        barra.addWidget(self.boton)
        barra.addWidget(salir)

        self.graf_pleth, self.curva = grafica("Pletismograma (infrarrojo)", "volumen sanguíneo (u.a.)", AZUL, VENTANA / FS)
        self.graf_pleth.getAxis("left").setStyle(showValues=False)
        self.graf_pleth.getAxis("left").setTicks([[], []])
        self.graf_pleth.showGrid(x=True, y=False)
        caja_fc, self.valor_fc, self.corazon = tarjeta("Frecuencia cardiaca (lpm)", AZUL, "♥")
        self.corazon.setStyleSheet(estilo_numero(APAGADO))
        caja_sat, self.valor_sat, _ = tarjeta("SpO₂ · sin calibrar", VERDE, "%")
        caja_pi, self.valor_pi, _ = tarjeta("Índice de perfusión (%)", "#d0d0d0")
        self.graf_fc, self.curva_fc = grafica("Frecuencia cardiaca", "lpm", AZUL, TENDENCIA)
        self.graf_sat, self.curva_sat = grafica("SpO₂", "%", VERDE, TENDENCIA)
        self.graf_fc.setYRange(40, 160)
        self.graf_sat.setYRange(80, 100)
        self.zona_fc = zona(self.graf_fc, LIMITES_FC)
        self.zona_sat = zona(self.graf_sat, (SPO2_MINIMA, 100))

        tendencias = QHBoxLayout()
        tendencias.addWidget(self.graf_fc)
        tendencias.addWidget(self.graf_sat)
        izquierda, derecha = QVBoxLayout(), QVBoxLayout()
        izquierda.addWidget(self.graf_pleth, 2)
        izquierda.addLayout(tendencias, 1)
        for elemento in (caja_fc, caja_sat, caja_pi):
            derecha.addWidget(elemento)
        cuerpo = QHBoxLayout()
        cuerpo.addLayout(izquierda, 3)
        cuerpo.addLayout(derecha, 1)
        self.flecha = QToolButton(
            text="Variabilidad del pulso",
            checkable=True,
            arrowType=Qt.ArrowType.RightArrow,
            toolButtonStyle=Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
            toggled=self.alternar_variabilidad,
        )
        self.bloques, bloques = {}, QHBoxLayout()
        for nombre in HRV:
            caja, valor, escala, interpretacion = bloque(nombre)
            self.bloques[nombre] = valor, escala, interpretacion
            bloques.addWidget(caja)
        nota = QLabel(
            "Se estima con el pulso (PPG), no con ECG, y necesita 60 s de señal quieta. Rangos de referencia de "
            "adultos sanos en reposo (Nunan et al., 2010): varían con la edad y la persona.",
            wordWrap=True,
            styleSheet="color: #8a8a8a; font-size: 12px;",
        )
        self.panel_hrv = QWidget(visible=False)
        contenido = QVBoxLayout(self.panel_hrv)
        contenido.setContentsMargins(0, 0, 0, 0)
        contenido.addLayout(bloques)
        contenido.addWidget(nota)
        principal = QVBoxLayout(self)
        principal.addLayout(barra)
        principal.addLayout(cuerpo)
        principal.addWidget(self.flecha, alignment=Qt.AlignmentFlag.AlignLeft)
        principal.addWidget(self.panel_hrv)

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
            self.inicio = datos[0, 0] / FS
        filtrado, self.filtro = sosfilt(SOS, datos[:, 2], zi=self.filtro)
        self.rojo.extend(datos[:, 1])
        self.ir.extend(datos[:, 2])
        self.ir_hrv.extend(datos[:, 2])
        self.vista.extend(-filtrado)
        self.tiempo.extend(datos[:, 0] / FS)
        self.curva.setData(np.array(self.tiempo), np.array(self.vista))
        avanzar(self.graf_pleth, self.inicio, self.tiempo[-1], VENTANA / FS)
        if self.midiendo:
            self.detectar_latidos(len(nuevas))

    def detectar_latidos(self, nuevas):
        vista, tiempo = np.array(self.vista), np.array(self.tiempo)
        reciente = vista[-3 * FS:]
        umbral = (reciente.max() + reciente.min()) / 2
        cruces = np.flatnonzero((vista[:-1] < umbral) & (vista[1:] >= umbral)) + 1
        for k in cruces[cruces >= len(vista) - nuevas]:
            if tiempo[k] - self.ultimo_latido >= 0.6 * 60 / self.fc[-1]:
                self.ultimo_latido = tiempo[k]
                self.latir()

    def latir(self):
        self.corazon.setStyleSheet(estilo_numero(ROJO))
        QTimer.singleShot(150, self.corazon, lambda: self.corazon.setStyleSheet(estilo_numero(APAGADO)))

    def calcular(self):
        self.hora.setText(f"{datetime.now():%H:%M:%S}")
        rojo, ir = np.array(self.rojo), np.array(self.ir)
        calidad = None
        if not self.hilo.is_alive():
            estado = "Desconectado"
        elif len(ir) < VENTANA:
            estado = "Llenando ventana"
        elif ir.min() < DEDO_MINIMO:
            estado = "Sin dedo"
        else:
            calidad = calidad_senal(ir)
            estado = "Midiendo" if calidad >= CALIDAD_MINIMA else "Señal poco fiable"
        self.midiendo = estado == "Midiendo"
        if estado in ("Sin dedo", "Desconectado"):
            self.ir_hrv.clear()
        self.mostrar_variabilidad()
        grabando = f" · <span style='color: {ROJO};'>● GRABANDO</span>" if self.archivo else ""
        detalle = "" if calidad is None else f" (calidad {calidad:.2f})"
        self.estado.setText(f"{self.origen} · {estado}{detalle}{grabando}")

        if estado != "Midiendo":
            for valor in (self.valor_fc, self.valor_sat, self.valor_pi):
                valor.setText("--")
            return
        self.fc.append(frecuencia_cardiaca(ir))
        self.sat.append(spo2(rojo, ir))
        self.valor_fc.setText(f"{self.fc[-1]:.0f}")
        self.valor_sat.setText(f"{self.sat[-1]:.0f}")
        self.valor_pi.setText(f"{indice_perfusion(ir):.1f}")
        self.tiempo_tendencia.append(self.tiempo[-1])
        self.curva_fc.setData(list(self.tiempo_tendencia), list(self.fc))
        self.curva_sat.setData(list(self.tiempo_tendencia), list(self.sat))
        for grafica_tendencia in (self.graf_fc, self.graf_sat):
            avanzar(grafica_tendencia, self.inicio, self.tiempo_tendencia[-1], TENDENCIA)

    def alternar_variabilidad(self, abierto):
        self.flecha.setArrowType(Qt.ArrowType.DownArrow if abierto else Qt.ArrowType.RightArrow)
        self.panel_hrv.setVisible(abierto)

    def mostrar_variabilidad(self):
        completa = len(self.ir_hrv) == VENTANA_HRV
        medidas = variabilidad(np.array(self.ir_hrv)) if completa else None
        for nombre, medida in zip(HRV, medidas or (None, None)):
            valor, escala, interpretacion = self.bloques[nombre]
            activa = None if medida is None else zona_hrv(medida, HRV[nombre][1])
            valor.setText("--" if medida is None else f"{medida:.0f}")
            for i, etiqueta in enumerate(escala):
                etiqueta.setStyleSheet(estilo_zona(COLORES_ZONA[i], i == activa))
            if medida is not None:
                interpretacion.setText(HRV[nombre][2][activa])
            elif completa:
                interpretacion.setText("Señal insuficiente: hay movimiento o ruido.")
            else:
                interpretacion.setText(f"Acumulando señal: {len(self.ir_hrv) // FS} / {VENTANA_HRV // FS} s")

    def configurar(self):
        ajustes = Ajustes(self, self.zona_fc.getRegion(), self.zona_sat.getRegion()[0])
        if ajustes.exec():
            self.fijar_limites((ajustes.fc_min.value(), ajustes.fc_max.value()), ajustes.spo2_min.value())

    def fijar_limites(self, limites_fc, spo2_minima):
        self.zona_fc.setRegion(limites_fc)
        self.zona_sat.setRegion((spo2_minima, 100))

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
