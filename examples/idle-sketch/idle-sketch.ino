// Deliberate replacement firmware for stopping autonomous LED examples.
#include <Arduino_LED_Matrix.h>
Arduino_LED_Matrix matrix;

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);
  matrix.begin();
  matrix.clear();
}

void loop() { delay(1000); }
