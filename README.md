# Pulxo-UES

Prototipo de pulsioxímetro con el sensor óptico MAX30102 y un Arduino Nano. El Arduino lee la luz roja e infrarroja que vuelve del dedo y la envía por USB a una aplicación en Python. La aplicación calcula la frecuencia cardiaca (FC), la saturación de oxígeno (SpO2) y el índice de perfusión (PI), y los muestra en vivo.

> **Aviso:** Pulxo-UES es un prototipo académico. Sus valores de SpO2 no están calibrados contra gasometría arterial y no deben usarse para decisiones médicas.

## Cómo funciona

```
MAX30102 ──I²C──▶ Arduino Nano ──USB (115200 baudios, 100 muestras/s)──▶ lector ─▶ procesamiento ─▶ interfaz
```

1. El MAX30102 enciende por turnos un LED rojo (660 n   m) y uno infrarrojo (880 nm) y mide con su fotodiodo cuánta luz regresa.
2. El Arduino envía cada muestra como una línea `n,rojo,ir`.
3. La aplicación filtra las señales, calcula FC, SpO2 y PI, y los muestra en un panel en vivo que también puede grabar la sesión.

## Hardware

- Sensor MAX30102
- Arduino Nano
- Protoboard, cables y cable USB

| MAX30102 | Arduino Nano |
|---|---|
| VIN | 5V (comprueba qué tensión admite tu módulo) |
| GND | GND |
| SDA | A4 |
| SCL | A5 |

## Firmware

1. En el Arduino IDE, instala desde el Gestor de bibliotecas la **SparkFun MAX3010x Pulse and Proximity Sensor Library**.
2. Abre `firmware/firmware.ino`, elige la placa **Arduino Nano** y cárgalo.

Configuración del sensor:
- **LED:** unos 12 mA.
- **Muestreo:** 400 muestras/s promediadas de 4 en 4, lo que da 100 muestras/s.
- **ADC:** pulso de 411 µs (18 bits) y rango de 4096 nA.

Al arrancar, el firmware envía dos líneas de cabecera que empiezan por `#` y después una línea `n,rojo,ir` por muestra. Si no encuentra el sensor, envía `# ERROR: MAX30102 no encontrado` y se detiene.

## Aplicación en Python

Requiere Python 3.12. Instalación:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Uso

Antes de empezar, cierra el Monitor Serie del Arduino IDE, porque el puerto solo lo puede usar un programa a la vez. El nombre del puerto (`COM5` en los ejemplos) aparece en el Arduino IDE, en **Herramientas → Puerto**.

| Comando | Qué hace |
|---|---|
| `python app/interfaz.py COM5` | Abre el panel en vivo: pletismograma (curva de pulso), FC, SpO2, PI y tendencias del último minuto. La flecha **Variabilidad del pulso** despliega RMSSD y SDNN con su interpretación. **Grabar** guarda la sesión en `sesiones/`. |
| `python app/lector.py COM5` | Graba la sesión en un CSV de `sesiones/` sin interfaz. Se termina con Ctrl+C. |
| `python app/procesamiento.py sesiones/<archivo>.csv` | Calcula la FC y la SpO2 de una grabación. |
| `python app/validacion_bidmc.py datos/bidmc` | Compara la FC, el RMSSD y el SDNN calculados con el PPG contra los del ECG, con los registros de la base pública BIDMC (PhysioNet). Imprime sesgo, MAE, RMSE y r, y guarda los gráficos Bland-Altman en `validacion/`. |

La barra superior del panel indica el estado:
- **Llenando ventana:** los primeros 10 s.
- **Sin dedo:** la señal infrarroja está por debajo del umbral de detección.
- **Señal poco fiable:** hay dedo, pero la calidad de la señal está por debajo de 0.5. Junto al estado se muestra la calidad actual.
- **Midiendo:** el panel muestra valores.
- **Desconectado:** se perdió el puerto, por ejemplo porque se desenchufó el cable USB.

Fuera de **Midiendo**, las tarjetas muestran `--`.

### Formato de las grabaciones

Las grabaciones son archivos CSV con las columnas `n,rojo,ir`:
- `n` es el contador de muestras del Arduino. Un salto en `n` indica muestras perdidas.
- `rojo` e `ir` están en cuentas del ADC.

La carpeta `sesiones/` no se sube al repositorio, porque contiene datos de salud.

## Procesamiento

- **Filtro de cálculo:** pasa-banda Butterworth de orden 4, con −6 dB en 0.5 y 4 Hz (30 y 240 lpm), aplicado en ambos sentidos (fase cero). Separa el pulso del nivel continuo, de la respiración y del ruido rápido.
- **Pletismograma:** curva del canal infrarrojo, invertida para que la sístole quede hacia arriba y filtrada en tiempo real con un pasa-altos de primer orden en 0.5 Hz y un pasa-bajos Butterworth de orden 2 en 8 Hz, con un retraso de unas decenas de milisegundos. La banda más ancha que la de cálculo conserva la forma de la onda, incluida la muesca dícrota. Como en los monitores comerciales, se autoescala y no tiene escala vertical: la amplitud cuantitativa es el índice de perfusión.
- **Frecuencia cardiaca:** FC = 60 · 100 / L, donde L es el retardo, en muestras, del primer pico de la autocorrelación de la señal infrarroja filtrada cuya altura es al menos la mitad del máximo, buscado entre 30 y 240 lpm. Tomar el primer pico, y no el máximo, evita que se elija el retardo de 2 o 3 latidos cuando la amplitud del pulso varía, por ejemplo con la respiración. A diferencia del conteo de picos, no se confunde con la muesca dícrota, que da dos picos por latido. Como L es un número entero de muestras, el error de redondeo es como máximo ±FC²/12 000 lpm: ±0.3 lpm a 60 lpm y ±1.9 lpm a 150 lpm.
- **SpO2:** R = (AC/DC rojo) / (AC/DC infrarrojo), donde AC es la desviación típica de la señal filtrada y DC la media de la señal sin filtrar. SpO2 = 110 − 25·R es la recta del diseño de referencia TIDA-00301 de Texas Instruments, basada en las curvas de calibración de Nellcor OxiMax (2003). No está calibrada para este sensor.
- **Calidad de señal:** autocorrelación de la señal infrarroja filtrada en el período del pulso, dividida entre su valor en retardo cero. Vale cerca de 1 con un pulso regular y cerca de 0 con ruido o señal plana. Por debajo de `CALIDAD_MINIMA` (0.5) el panel no muestra FC, SpO2 ni índice de perfusión. La variabilidad no depende de este umbral: un ritmo irregular también baja la calidad, y con él se perdería la variabilidad alta real.
- **Índice de perfusión:** pico a pico de la señal infrarroja filtrada, sin el primer ni el último segundo de la ventana, dividido entre la media de la señal sin filtrar y multiplicado por 100.
- **Variabilidad del pulso (RMSSD y SDNN):** se detectan los picos del pulso en la señal infrarroja filtrada, con interpolación parabólica para pasar de los 10 ms de la muestra a una fracción de ella. Se descartan los intervalos que se alejan más de 30 % de la mediana. RMSSD es la raíz cuadrática media de las diferencias entre intervalos sucesivos; SDNN es la desviación típica de los intervalos. Se calcula sobre los últimos 60 s sin interrupción de dedo, así que el panel muestra `--` hasta acumularlos. Es variabilidad del pulso (PPG), no HRV de ECG. Las zonas del panel (RMSSD 19–75 ms, SDNN 32–93 ms) son los rangos de referencia de adultos sanos en reposo de Nunan et al. (2010) y varían con la edad y la persona.
- **En vivo:** cada segundo se calcula sobre los últimos 10 s, así que los valores mostrados son el promedio de esos 10 s.

## Pruebas

```
python app/test_lector.py
python app/test_procesamiento.py
python app/test_interfaz.py
python app/test_validacion_bidmc.py
```

Cada prueba imprime `OK` si todo está bien.

## Estructura

```
firmware/firmware.ino   adquisición en el Arduino
app/lector.py           lectura del puerto serie y grabación en CSV
app/procesamiento.py    filtrado, FC, SpO2 e índice de perfusión
app/interfaz.py         panel en vivo
app/validacion_bidmc.py comparación contra la base pública BIDMC
app/test_*.py           pruebas automáticas
datos/                  bases públicas descargadas (no se suben al repositorio)
validacion/             gráficos de la validación
docs/                   documentación de apoyo
sesiones/               grabaciones (no se suben al repositorio)
```

## Estado

- ✅ Adquisición, procesamiento e interfaz implementados, con pruebas automáticas.
- ⏳ Prueba con el sensor real.
- ⏳ Ajuste del umbral de detección de dedo (`DEDO_MINIMO` en `app/interfaz.py`).
- ⏳ Calibración de la SpO2 contra un oxímetro comercial.
