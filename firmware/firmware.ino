#include <Wire.h>
#include "MAX30105.h"  

const byte BRILLO_LED  = 60;   
const byte PROMEDIO    = 4;    
const int  TASA_SENSOR = 400;  
const int  FS = TASA_SENSOR / PROMEDIO;  

MAX30105 sensor;
unsigned long n = 0;

void setup() {
  Serial.begin(115200);

  if (!sensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println(F("# ERROR: MAX30102 no encontrado. Revisa las conexiones."));
    while (true) {}  
  }
  sensor.setup(BRILLO_LED, PROMEDIO, 2, TASA_SENSOR, 411, 4096);

  Serial.print(F("# Pulxo-UES fs="));
  Serial.println(FS);
  Serial.println(F("# n,rojo,ir"));
}

void loop() {
  
  sensor.check(); 
  while (sensor.available()) {
    Serial.print(n++);
    Serial.print(',');
    Serial.print(sensor.getFIFORed());
    Serial.print(',');
    Serial.println(sensor.getFIFOIR());
    sensor.nextSample();
  }
}
