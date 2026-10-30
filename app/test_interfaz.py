import csv
import os
import tempfile
import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from interfaz import (
    COLORES_ZONA, ESTABILIZACION, HRV, LIMITES_FC, SPO2_MINIMA, TENDENCIA, VENTANA, VENTANA_HRV, Ajustes, Panel, estilo_zona, texto_cambio,
    zona_hrv,
)
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

parcial = Panel(iter(threading.Event().wait, None), "Prueba")
assert parcial.graf_fc.viewRange()[0] == [0, TENDENCIA], parcial.graf_fc.viewRange()[0]
for n in range(3 * FS):
    parcial.cola.put((n, 50000, 60000))
parcial.refrescar()
assert parcial.graf_pleth.viewRange()[0] == [0, VENTANA / FS], parcial.graf_pleth.viewRange()[0]
eje_y = parcial.graf_pleth.getAxis("left")
assert eje_y.isVisible() and eje_y.labelText == "volumen sanguíneo (u.a.)" and not eje_y.style["showValues"]

vacio = Panel(iter(threading.Event().wait, None), "Prueba")
ruido_ambiente = np.random.default_rng(1).normal(2000, 40, 3 * FS)
for n in range(3 * FS):
    vacio.cola.put((n, 1500, int(ruido_ambiente[n])))
vacio.refrescar()
assert len(vacio.curva.getData()[1]) == 3 * FS and not np.any(vacio.curva.getData()[1])

pulso_dedo = np.sin(2 * np.pi * 72 / 60 * np.arange(6 * FS) / FS)
for n in range(6 * FS):
    vacio.cola.put((3 * FS + n, 50000, int(60000 + 1200 * pulso_dedo[n])))
vacio.refrescar()
curva_dedo = vacio.curva.getData()[1][3 * FS:]
assert not np.any(curva_dedo[:ESTABILIZACION]) and np.abs(curva_dedo).max() < 3000, np.abs(curva_dedo).max()
assert np.corrcoef(curva_dedo[-2 * FS:], -pulso_dedo[-2 * FS:])[0, 1] > 0.9

pulso = np.sin(2 * np.pi * 72 / 60 * np.arange(VENTANA) / FS)
panel.grabar()
alimentar(50000 + 500 * pulso, 60000 + 1200 * pulso)
panel.grabar()
assert abs(int(panel.valor_fc.text()) - 72) <= 2, panel.valor_fc.text()
assert abs(float(panel.valor_sat.text()) - 97.5) <= 1, panel.valor_sat.text()
assert abs(float(panel.valor_pi.text()) - 4.0) < 0.2, panel.valor_pi.text()
assert "Midiendo" in panel.estado.text() and "calidad" in panel.estado.text(), panel.estado.text()

pleth = panel.curva.getData()[1][-5 * FS:]
assert np.corrcoef(pleth, -pulso[-5 * FS:])[0, 1] > 0.9
tiempo = panel.curva.getData()[0]
assert tiempo[0] == 0 and tiempo[-1] == (VENTANA - 1) / FS, (tiempo[0], tiempo[-1])
assert panel.curva_fc.getData()[0][-1] == (VENTANA - 1) / FS

with open(next(Path("sesiones").glob("*.csv")), newline="") as archivo:
    filas = list(csv.reader(archivo))
assert filas[0] == ["n", "rojo", "ir"]
assert len(filas) == VENTANA + 1

assert any(e.text() == "%" and e.styleSheet() == panel.valor_sat.styleSheet() for e in panel.findChildren(QLabel))

latidos = []
latir = panel.latir
panel.latir = lambda: latidos.append(1)
for n in range(VENTANA, VENTANA + 5 * FS):
    p = np.sin(2 * np.pi * 72 / 60 * n / FS)
    panel.cola.put((n, int(50000 + 500 * p), int(60000 + 1200 * p)))
panel.refrescar()
assert len(latidos) == 6, len(latidos)
apagado = panel.corazon.styleSheet()
latir()
assert panel.corazon.styleSheet() != apagado
app.processEvents()
QTest.qWait(300)
assert panel.corazon.styleSheet() == apagado

alimentar(np.full(VENTANA, 500), np.full(VENTANA, 600))
assert panel.valor_fc.text() == "--"
assert "Sin dedo" in panel.estado.text(), panel.estado.text()

assert panel.zona_fc.getRegion() == LIMITES_FC
assert panel.zona_sat.getRegion() == (SPO2_MINIMA, 100)

ajustes = Ajustes(panel, LIMITES_FC, SPO2_MINIMA)
ajustes.fc_min.setValue(500)
assert ajustes.fc_min.value() == LIMITES_FC[1] - 1
ajustes.fc_max.setValue(0)
assert ajustes.fc_max.value() == ajustes.fc_min.value() + 1
assert not ajustes.alarma.isEnabled()

panel.fijar_limites((60, 100), 92)
assert panel.zona_fc.getRegion() == (60, 100)
assert panel.zona_sat.getRegion() == (92, 100)

ruidoso = Panel(iter(threading.Event().wait, None), "Prueba")
azar = np.random.default_rng(5).normal(0, 300, VENTANA)
for n in range(VENTANA):
    ruidoso.cola.put((n, 50000, int(60000 + azar[n])))
ruidoso.refrescar()
ruidoso.calcular()
assert "Señal poco fiable" in ruidoso.estado.text(), ruidoso.estado.text()
assert ruidoso.valor_fc.text() == ruidoso.valor_sat.text() == ruidoso.valor_pi.text() == "--"
assert len(ruidoso.ir_hrv) == VENTANA

assert [zona_hrv(v, (19, 75)) for v in (5, 19, 40, 75, 120)] == [0, 1, 1, 2, 2]


def pulsos(rr, n):
    u = np.arange(n)[:, None] / FS - np.cumsum(rr)[None, :]
    return 60000 - 1200 * (np.exp(-((u - 0.15) / 0.07) ** 2) + 0.5 * np.exp(-((u - 0.45) / 0.09) ** 2)).sum(axis=1)


def panel_hrv(rr):
    p = Panel(iter(threading.Event().wait, None), "Prueba")
    ir = pulsos(rr, 62 * FS)
    for segundo in range(62):
        for n in range(segundo * FS, (segundo + 1) * FS):
            p.cola.put((n, 50000, int(ir[n])))
        p.refrescar()
        p.calcular()
        if segundo == 29:
            assert p.bloques["RMSSD"][0].text() == "--"
            assert "Acumulando señal: 30 / 60 s" in p.bloques["RMSSD"][2].text(), p.bloques["RMSSD"][2].text()
    return p


def encendidas(p, nombre):
    escala = p.bloques[nombre][1]
    return [i for i, e in enumerate(escala) if e.styleSheet() == estilo_zona(COLORES_ZONA[i], True)]


generador = np.random.default_rng(3)
for sigma, esperada in ((0, 0), (0.04, 1), (0.1, 2)):
    p = panel_hrv(0.8 + generador.normal(0, sigma, 80))
    for nombre in HRV:
        valor, _, interpretacion = p.bloques[nombre]
        assert valor.text() != "--", (sigma, nombre)
        zona = zona_hrv(float(valor.text()), HRV[nombre][1])
        assert encendidas(p, nombre) == [zona], (sigma, nombre, encendidas(p, nombre))
        assert interpretacion.text() == HRV[nombre][2][zona]
    assert encendidas(p, "RMSSD") == [esperada], (sigma, p.bloques["RMSSD"][0].text())

assert p.panel_hrv.isHidden() and p.flecha.arrowType() == Qt.ArrowType.RightArrow
p.flecha.click()
assert not p.panel_hrv.isHidden() and p.flecha.arrowType() == Qt.ArrowType.DownArrow
p.flecha.click()
assert p.panel_hrv.isHidden() and p.flecha.arrowType() == Qt.ArrowType.RightArrow

for n in range(62 * FS, 72 * FS):
    p.cola.put((n, 500, 600))
p.refrescar()
p.calcular()
assert "Sin dedo" in p.estado.text() and len(p.ir_hrv) == 0
assert p.bloques["RMSSD"][0].text() == "--" and encendidas(p, "RMSSD") == []

assert texto_cambio(99.7, 100, True) == "Cambio: +0 %" and texto_cambio(70, 100, True) == "Cambio: -30 %"
assert texto_cambio(-2.101, -2.1, False) == "Cambio: +0.00" and texto_cambio(-2.0, -2.1, False) == "Cambio: +0.10"
assert texto_cambio(None, 1, True) == texto_cambio(1, None, False) == "Cambio: --"

principal = Panel(iter(threading.Event().wait, None), "Prueba")
onda = principal.ventana_onda
assert onda.isHidden() and not onda.boton_base.isEnabled() and onda.tarjetas["b/a"][0].text() == "--"
diez = np.arange(VENTANA) / FS
desfase = diez[:, None] - np.arange(0, 11, 0.85)[None, :]
subida = np.clip(desfase, 0, None) / 0.05
forma = (subida ** 2 * np.exp(2 - subida)).sum(axis=1) / 4 + 0.25 * np.exp(-((desfase - 0.38) / 0.07) ** 2).sum(axis=1)
forma /= forma.max()
irregular = np.random.default_rng(0).normal(0, 15, VENTANA)


def alimentar_forma(inicio, escala):
    for k in range(VENTANA):
        principal.cola.put((inicio + k, int(50000 - 600 * escala * forma[k]), int(60000 - 1500 * escala * forma[k] + irregular[k])))
    principal.refrescar()
    principal.calcular()


alimentar_forma(0, 1)
assert "Midiendo" in principal.estado.text(), principal.estado.text()
principal.boton_onda.click()
assert not onda.isHidden() and onda.boton_base.isEnabled()
assert "latidos" in onda.estado.text(), onda.estado.text()
for nombre, (ahora, base, cambio) in onda.tarjetas.items():
    assert ahora.text() != "--" and base.text() == "Base: --" and cambio.text() == "Cambio: --", nombre
assert -1.0 < float(onda.tarjetas["b/a"][0].text()) < -0.7, onda.tarjetas["b/a"][0].text()
assert len(onda.puntos.data) == 5 and all(letra.isVisible() for letra in onda.letras)
assert len(onda.curvas_tendencia["PI"].getData()[0] or []) == 0

onda.boton_base.click()
assert onda.base is not None and onda.curva_pulso_base.getData()[0] is not None
assert onda.tarjetas["PI"][2].text() == "Cambio: +0 %" and onda.tarjetas["b/a"][2].text() == "Cambio: +0.00"

alimentar_forma(VENTANA, 0.6)
caida = float(onda.tarjetas["PI"][2].text().split()[1])
assert -45 < caida < -35, onda.tarjetas["PI"][2].text()
assert len(onda.curvas_tendencia["PI"].getData()[0]) >= 2

for n in range(2 * VENTANA, 3 * VENTANA):
    principal.cola.put((n, 500, 600))
principal.refrescar()
principal.calcular()
assert "Esperando" in onda.estado.text() and onda.tarjetas["AGI"][0].text() == "--"
assert onda.base is not None and onda.tarjetas["AGI"][1].text() != "Base: --"
assert len(onda.puntos.data) == 0 and not any(letra.isVisible() for letra in onda.letras)
principal.close()
assert onda.isHidden()

print("OK")
