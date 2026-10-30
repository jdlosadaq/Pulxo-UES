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
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QStyle, QToolButton, QVBoxLayout, QWidget,
)
from scipy.signal import butter, sosfilt, sosfilt_zi

from lector import BAUDIO, FS, muestras, simulador
from procesamiento import (
    CALIDAD_MINIMA, calidad_senal, frecuencia_cardiaca, indice_perfusion, morfologia, spo2, suavizar, variabilidad,
)

VENTANA = 10 * FS
VENTANA_HRV = 60 * FS
TENDENCIA = 60
DEDO_MINIMO = 50000
ESTABILIZACION = 2 * FS
ESCALA_MINIMA = 100
MARGEN_ESCALA = 1.5
HISTERESIS_ESCALA = 0.7
LIMITES_FC = (50, 120)
SPO2_MINIMA = 90
SOS = np.vstack([butter(1, 0.5, btype="high", fs=FS, output="sos"), butter(2, 8, fs=FS, output="sos")])

AZUL, ROJO, VERDE = "#f74040", "#e5534b", "#1e9e3c"
ZONA = (210, 153, 34, 45)
APAGADO = "#e3c4c6"
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
ANTES, DESPUES = 25, 75
COLORES_ONDA = ("#4aa3ff", "#e5534b", "#d29922", "#c678dd", VERDE)
CAMBIOS = (
    ("b/a", "Profundidad de la onda b respecto a la onda a", "{:.2f}", False),
    ("AGI", "Combina las cinco ondas: (b − c − d − e) / a", "{:.2f}", False),
    ("PI", "Índice de perfusión (%): baja si los vasos del dedo se contraen", "{:.2f}", True),
    ("FC", "Frecuencia cardiaca (lpm)", "{:.0f}", True),
)
TENDENCIAS = (("PI", VERDE), ("FC", AZUL), ("b/a", "#4aa3ff"))
HISTORIA = 300
SEGUNDOS_BASE = 30
ESTILO = """
QWidget { background: #f5f6f8; color: #24272b; font-size: 14px; }
QFrame#tarjeta { background: #ffffff; border: 1px solid #dcdfe4; border-radius: 6px; }
QFrame#tarjeta QLabel { background: transparent; border: none; }
QPushButton { background: #ffffff; border: 1px solid #c4c8ce; border-radius: 4px; padding: 6px 14px; }
QPushButton:hover { background: #e9ebee; }
QCheckBox:disabled { color: #a0a4aa; }
QToolButton { background: transparent; border: none; font-weight: bold; }
"""

pg.setConfigOptions(background="#f5f6f8", foreground="#24272b", antialias=True)


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
    return "background: transparent; color: #8a8f96; border: 1px solid #c4c8ce; border-radius: 4px; padding: 4px;"


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


def tarjeta_cambio(nombre, descripcion):
    caja = QFrame(objectName="tarjeta")
    ahora = QLabel("--", styleSheet="font-size: 36px; font-weight: bold;")
    base = QLabel("Base: --", styleSheet="color: #6b7078;")
    cambio = QLabel("Cambio: --", styleSheet="font-size: 18px; font-weight: bold;")
    cabecera, pie = QHBoxLayout(), QHBoxLayout()
    cabecera.addWidget(QLabel(nombre, styleSheet="font-size: 20px; font-weight: bold;"))
    cabecera.addStretch()
    cabecera.addWidget(ahora)
    pie.addWidget(base)
    pie.addStretch()
    pie.addWidget(cambio)
    columna = QVBoxLayout(caja)
    columna.addLayout(cabecera)
    columna.addWidget(QLabel(descripcion, wordWrap=True, styleSheet="color: #6b7078; font-size: 12px;"))
    columna.addLayout(pie)
    return caja, ahora, base, cambio


def cambio_relativo(valor, base):
    return 100 * (valor - base) / abs(base)


def texto_cambio(valor, base, relativo):
    if valor is None or base is None:
        return "Cambio: --"
    if relativo:
        return f"Cambio: {round(cambio_relativo(valor, base)):+d} %"
    return f"Cambio: {round(valor - base, 2) + 0:+.2f}"


class VentanaOnda(QWidget):
    def __init__(self, padre):
        super().__init__(padre, Qt.WindowType.Window, windowTitle="Pulxo-UES · Onda de pulso", styleSheet=ESTILO)
        self.tiempo = (np.arange(ANTES + DESPUES) - ANTES) * 1000 / FS
        self.historia = deque(maxlen=HISTORIA)
        self.base = self.ultimo = None
        self.estado = QLabel(styleSheet="color: #9a6700;")
        self.boton_base = QPushButton("Fijar línea base", enabled=False, clicked=self.fijar_base)
        self.graf_pulso = pg.PlotWidget(title="Pulso promedio (normalizado)")
        self.graf_apg = pg.PlotWidget(title="Segunda derivada del pulso (APG), escalada a la onda a")
        for g in (self.graf_pulso, self.graf_apg):
            g.setLabel("bottom", "tiempo desde la onda a (ms)")
            g.getAxis("left").setStyle(showValues=False)
            g.getAxis("left").setTicks([[], []])
            g.showGrid(x=True, y=False, alpha=0.2)
            g.getViewBox().setDefaultPadding(0.15)
        self.graf_apg.setXLink(self.graf_pulso)
        self.graf_apg.addLine(y=0, pen=pg.mkPen("#555555"))
        punteado = pg.mkPen("#8a8a8a", width=2, style=Qt.PenStyle.DashLine)
        self.curva_pulso_base = self.graf_pulso.plot(pen=punteado)
        self.curva_apg_base = self.graf_apg.plot(pen=punteado)
        self.curva_pulso = self.graf_pulso.plot(pen=pg.mkPen(AZUL, width=3))
        self.curva_apg = self.graf_apg.plot(pen=pg.mkPen("#24272b", width=3))
        self.puntos = pg.ScatterPlotItem(size=16, pen=pg.mkPen("#f5f6f8", width=2))
        self.graf_apg.addItem(self.puntos)
        self.letras, self.guias = [], []
        for letra, color in zip("abcde", COLORES_ONDA):
            texto = pg.TextItem(html=f"<b style='font-size: 18px; color: {color};'>{letra}</b>", anchor=(0.5, 1.2 if letra in "ace" else -0.2))
            guia = pg.InfiniteLine(angle=90, pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine))
            self.graf_apg.addItem(texto)
            self.graf_pulso.addItem(guia)
            self.letras.append(texto)
            self.guias.append(guia)
        self.graf_tendencia = pg.PlotWidget(title="Cambio respecto a tu línea base (%)")
        self.graf_tendencia.setLabel("bottom", "tiempo", "s")
        self.graf_tendencia.getAxis("bottom").enableAutoSIPrefix(False)
        self.graf_tendencia.setLabel("left", "%")
        self.graf_tendencia.showGrid(x=True, y=True, alpha=0.2)
        self.graf_tendencia.addLine(y=0, pen=pg.mkPen("#8a8a8a", style=Qt.PenStyle.DashLine))
        self.graf_tendencia.addLegend(offset=(10, 10))
        self.curvas_tendencia = {nombre: self.graf_tendencia.plot(pen=pg.mkPen(color, width=2), name=nombre) for nombre, color in TENDENCIAS}
        self.tarjetas, tarjetas = {}, QGridLayout()
        for k, (nombre, descripcion, _, _) in enumerate(CAMBIOS):
            caja, ahora, base, cambio = tarjeta_cambio(nombre, descripcion)
            self.tarjetas[nombre] = ahora, base, cambio
            tarjetas.addWidget(caja, k // 2, k % 2)
        pasos = QLabel(
            "1. Quédate quieto 30 s.  2. Pulsa «Fijar línea base».  3. Haz el estímulo: respirar lento o restar de 7 en 7.  "
            "4. Mira cómo cambia tu onda.",
            wordWrap=True,
        )
        control = QHBoxLayout()
        control.addWidget(self.boton_base)
        control.addWidget(pasos, 1)
        derecha = QVBoxLayout()
        derecha.addLayout(tarjetas)
        derecha.addLayout(control)
        derecha.addWidget(self.graf_tendencia, 1)
        graficas = QVBoxLayout()
        graficas.addWidget(self.graf_pulso)
        graficas.addWidget(self.graf_apg)
        cuerpo = QHBoxLayout()
        cuerpo.addLayout(graficas, 1)
        cuerpo.addLayout(derecha, 1)
        nota = QLabel(
            "Gris punteado: tu línea base. Color: ahora. Cada persona se compara consigo misma, no con otras personas ni con "
            "su edad. La forma de la onda también cambia con la presión del dedo sobre el sensor, la temperatura de la mano y "
            "el movimiento: mantenlos constantes durante la medición.",
            wordWrap=True,
            styleSheet="color: #6b7078; font-size: 12px;",
        )
        principal = QVBoxLayout(self)
        principal.addWidget(QLabel("¿CÓMO CAMBIA TU ONDA DE PULSO?", styleSheet="font-size: 18px; font-weight: bold;"))
        principal.addWidget(QLabel(
            "b/a y AGI: indicador de morfología de la onda de pulso asociado al envejecimiento vascular, comparado con tu propia línea base.",
            wordWrap=True,
            styleSheet="color: #6b7078;",
        ))
        principal.addWidget(self.estado)
        principal.addLayout(cuerpo, 1)
        principal.addWidget(nota)
        self.resize(1400, 860)
        self.actualizar(None)

    def actualizar(self, ir, instante=0):
        if ir is None:
            self.mostrar(None, None, "Esperando señal fiable: el panel principal debe estar en «Midiendo».")
            return
        resultado = morfologia(suavizar(-ir))
        if resultado is None:
            self.mostrar(None, None, "No se encontraron las ondas a–e en los últimos 10 s.")
            return
        valores = {"b/a": resultado[3][0], "AGI": resultado[3][4], "PI": indice_perfusion(ir), "FC": frecuencia_cardiaca(ir)}
        self.historia.append((instante, valores))
        self.ultimo = resultado
        self.boton_base.setEnabled(True)
        self.mostrar(resultado, valores, f"Promedio de {resultado[4]} latidos de los últimos 10 s")

    def fijar_base(self):
        final = self.historia[-1][0]
        recientes = [valores for instante, valores in self.historia if instante >= final - SEGUNDOS_BASE]
        self.base = {nombre: float(np.nanmedian([v[nombre] for v in recientes])) for nombre, *_ in CAMBIOS}
        pulso, apg_medio, marcas, _, _ = self.ultimo
        self.curva_pulso_base.setData(self.tiempo, (pulso - pulso.min()) / np.ptp(pulso))
        self.curva_apg_base.setData(self.tiempo, apg_medio / apg_medio[int(marcas[0])])
        self.mostrar(self.ultimo, self.historia[-1][1], self.estado.text())

    def mostrar(self, resultado, valores, texto):
        self.estado.setText(texto + ("" if self.base is None or " · línea base" in texto else f" · línea base: mediana de {SEGUNDOS_BASE} s"))
        pulso, apg_medio, marcas, _, _ = resultado or (None, None, np.full(5, np.nan), None, 0)
        if pulso is None:
            self.curva_pulso.setData([], [])
            self.curva_apg.setData([], [])
        else:
            apg_medio = apg_medio / apg_medio[int(marcas[0])]
            self.curva_pulso.setData(self.tiempo, (pulso - pulso.min()) / np.ptp(pulso))
            self.curva_apg.setData(self.tiempo, apg_medio)
        visibles = [k for k in range(5) if not np.isnan(marcas[k])]
        self.puntos.setData(
            x=[self.tiempo[int(marcas[k])] for k in visibles],
            y=[apg_medio[int(marcas[k])] for k in visibles],
            brush=[COLORES_ONDA[k] for k in visibles],
        )
        for k, (letra, guia) in enumerate(zip(self.letras, self.guias)):
            letra.setVisible(k in visibles)
            guia.setVisible(k in visibles)
            if k in visibles:
                letra.setPos(self.tiempo[int(marcas[k])], apg_medio[int(marcas[k])])
                guia.setValue(self.tiempo[int(marcas[k])])
        for nombre, _, formato, relativo in CAMBIOS:
            ahora, base, cambio = self.tarjetas[nombre]
            valor = None if valores is None or np.isnan(valores[nombre]) else valores[nombre]
            referencia = None if self.base is None or np.isnan(self.base[nombre]) else self.base[nombre]
            ahora.setText("--" if valor is None else formato.format(valor))
            base.setText("Base: --" if referencia is None else f"Base: {formato.format(referencia)}")
            cambio.setText(texto_cambio(valor, referencia, relativo))
        for nombre, curva in self.curvas_tendencia.items():
            if self.base is None:
                curva.setData([], [])
                continue
            puntos = [(instante, cambio_relativo(v[nombre], self.base[nombre])) for instante, v in self.historia if not np.isnan(v[nombre])]
            curva.setData([p[0] for p in puntos], [p[1] for p in puntos])


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
        self.archivo = self.escritor = self.filtro = self.inicio = None
        self.con_dedo = 0
        self.midiendo, self.ultimo_latido = False, -np.inf

        self.hora, self.estado = QLabel(), QLabel()
        icono = self.style().standardIcon
        self.boton = QPushButton(icono(QStyle.StandardPixmap.SP_DialogSaveButton), "Grabar", clicked=self.grabar)
        ajustes = QPushButton("Ajustes", clicked=self.configurar)
        self.boton_onda = QPushButton("Onda de pulso ↗", clicked=self.abrir_onda)
        self.ventana_onda = VentanaOnda(self)
        salir = QPushButton("Salir", clicked=self.close)
        barra = QHBoxLayout()
        barra.addWidget(self.hora)
        barra.addWidget(self.estado)
        barra.addStretch()
        barra.addWidget(QLabel("PULXO-UES · PULSIOXÍMETRO MAX30102", styleSheet="font-size: 16px; font-weight: bold;"))
        barra.addStretch()
        barra.addWidget(self.boton_onda)
        barra.addWidget(ajustes)
        barra.addWidget(self.boton)
        barra.addWidget(salir)

        self.graf_pleth, self.curva = grafica("Pletismograma (infrarrojo)", "volumen sanguíneo (u.a.)", AZUL, VENTANA / FS)
        self.graf_pleth.getAxis("left").setStyle(showValues=False)
        self.graf_pleth.getAxis("left").setTicks([[], []])
        self.graf_pleth.showGrid(x=True, y=False)
        self.escala = ESCALA_MINIMA
        self.graf_pleth.setYRange(-ESCALA_MINIMA, ESCALA_MINIMA, padding=0)
        caja_fc, self.valor_fc, self.corazon = tarjeta("Frecuencia cardiaca (lpm)", AZUL, "♥")
        self.corazon.setStyleSheet(estilo_numero(APAGADO))
        caja_sat, self.valor_sat, _ = tarjeta("SpO₂ · sin calibrar", VERDE, "%")
        caja_pi, self.valor_pi, _ = tarjeta("Índice de perfusión (%)", "#24272b")
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
            styleSheet="color: #6b7078; font-size: 12px;",
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
        if self.inicio is None:
            self.inicio = datos[0, 0] / FS
        self.rojo.extend(datos[:, 1])
        self.ir.extend(datos[:, 2])
        self.ir_hrv.extend(datos[:, 2])
        self.vista.extend(self.filtrar(datos[:, 2]))
        self.ajustar_escala()
        self.tiempo.extend(datos[:, 0] / FS)
        self.curva.setData(np.array(self.tiempo), np.array(self.vista))
        avanzar(self.graf_pleth, self.inicio, self.tiempo[-1], VENTANA / FS)
        if self.midiendo:
            self.detectar_latidos(len(nuevas))

    def filtrar(self, ir):
        salida = np.zeros(len(ir))
        for k, valor in enumerate(ir):
            if valor < DEDO_MINIMO:
                self.filtro, self.con_dedo = None, 0
                continue
            if self.filtro is None:
                self.filtro = sosfilt_zi(SOS) * valor
            filtrado, self.filtro = sosfilt(SOS, [valor], zi=self.filtro)
            self.con_dedo += 1
            if self.con_dedo > ESTABILIZACION:
                salida[k] = -filtrado[0]
        return salida

    def ajustar_escala(self):
        objetivo = max(ESCALA_MINIMA, MARGEN_ESCALA * np.percentile(np.abs(self.vista), 98))
        if objetivo > self.escala or objetivo < HISTERESIS_ESCALA * self.escala:
            self.escala = objetivo
            self.graf_pleth.setYRange(-objetivo, objetivo, padding=0)

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
        if self.ventana_onda.isVisible():
            self.ventana_onda.actualizar(ir if self.midiendo else None, self.tiempo[-1] if self.tiempo else 0)
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

    def abrir_onda(self):
        self.ventana_onda.show()
        self.ventana_onda.raise_()
        self.ventana_onda.activateWindow()
        self.ventana_onda.actualizar(np.array(self.ir) if self.midiendo else None, self.tiempo[-1] if self.tiempo else 0)

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
        self.ventana_onda.close()
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
