
/*
  RB2 - ESP32 WROOM
  Version complète corrigée :
  OTA + Wi-Fi diagnostic + Pan-Tilt + Moteurs + Encodeurs + commande directe dG,D
  + Watchdog moteur 1000 ms

  IMPORTANT :
  - Si le ESP32 n'est pas connecté au Wi-Fi, OTA ne fonctionnera pas.
  - Dans ce cas, téléverser ce code par USB depuis Arduino IDE.
  - Ensuite, vérifier dans minicom si le Wi-Fi se connecte.

  Pan  : GPIO19
  Tilt : GPIO18

  Moteurs BTS7960 :
    Gauche avant : GPIO17
    Gauche recul : GPIO16
    Droit avant  : GPIO22
    Droit recul  : GPIO21

  Encodeurs :
    Avant gauche   : A GPIO32, B GPIO33
    Avant droit    : A GPIO27, B GPIO14
    Arrière droit  : A GPIO34, B GPIO35
    Arrière gauche : A GPIO25, B GPIO26

  Commandes :
    status       -> état complet
    help         -> aide

    center       -> pan 90 / tilt 90
    p90          -> pan à 90
    p120         -> pan à 120
    t90          -> tilt à 90
    t68          -> tilt à 68
    t40          -> tilt forcé à 68

    stop         -> arrêt moteurs
    f20          -> avance 20 %
    b20          -> recul 20 %
    l20          -> rotation gauche 20 %
    r20          -> rotation droite 20 %

    ml20         -> moteur gauche avance 20 %
    mr20         -> moteur droit avance 20 %
    gl20         -> moteur gauche recule 20 %
    gr20         -> moteur droit recule 20 %

    d20,20       -> commande directe gauche,droite
    d-20,-20     -> recul direct
    d-20,20      -> rotation gauche
    d20,-20      -> rotation droite
    d0,0         -> arrêt

    enc          -> affiche encodeurs
    encreset     -> remet encodeurs à zéro

    mtest        -> test moteur court

  Watchdog moteur :
    Si aucune commande moteur n'est reçue pendant 1000 ms,
    les moteurs sont arrêtés automatiquement.
*/

#include <WiFi.h>
#include <ArduinoOTA.h>
#include <ESP32Servo.h>

// =====================================================
// WIFI / OTA
// =====================================================

const char* ssid = "WIFI-MAISON-2.4G";
const char* password = "*****";

const char* otaHostname = "RB2-ESP32";
const char* otaPassword = "****";

// =====================================================
// PAN-TILT
// =====================================================

const int PAN_PIN  = 19;
const int TILT_PIN = 18;

const int PAN_MIN = 0;
const int PAN_MAX = 180;

const int TILT_MIN = 68;
const int TILT_MAX = 180;

int panPos = 90;
int tiltPos = 90;

Servo panServo;
Servo tiltServo;

// =====================================================
// MOTEURS
// =====================================================

const int LEFT_FWD_PIN  = 17;
const int LEFT_REV_PIN  = 16;
const int RIGHT_FWD_PIN = 22;
const int RIGHT_REV_PIN = 21;

const int MOTOR_PWM_FREQ = 20000;
const int MOTOR_PWM_RES  = 8;
const int MOTOR_MAX_PWM  = 255;

int leftMotorPercent = 0;
int rightMotorPercent = 0;

// =====================================================
// WATCHDOG MOTEURS
// =====================================================

const unsigned long MOTOR_WATCHDOG_TIMEOUT_MS = 1000;
unsigned long lastMotorCommandMs = 0;
bool motorWatchdogArmed = false;

// =====================================================
// ENCODEURS
// =====================================================

const int ENC_FL_A = 32;
const int ENC_FL_B = 33;

const int ENC_FR_A = 27;
const int ENC_FR_B = 14;

const int ENC_RR_A = 34;
const int ENC_RR_B = 35;

const int ENC_RL_A = 25;
const int ENC_RL_B = 26;

volatile long encFL = 0;
volatile long encFR = 0;
volatile long encRR = 0;
volatile long encRL = 0;

volatile uint8_t lastFL = 0;
volatile uint8_t lastFR = 0;
volatile uint8_t lastRR = 0;
volatile uint8_t lastRL = 0;

portMUX_TYPE encoderMux = portMUX_INITIALIZER_UNLOCKED;

// =====================================================
// VARIABLES GLOBALES
// =====================================================

String serialLine = "";
bool wifiOk = false;
bool otaActive = false;

// =====================================================
// OUTILS
// =====================================================

int clampInt(int value, int minimum, int maximum) {
  if (value < minimum) return minimum;
  if (value > maximum) return maximum;
  return value;
}

int percentToPwm(int percent) {
  percent = clampInt(percent, 0, 100);
  return map(percent, 0, 100, 0, MOTOR_MAX_PWM);
}

// =====================================================
// WATCHDOG MOTEURS
// =====================================================

void armMotorWatchdog() {
  lastMotorCommandMs = millis();
  motorWatchdogArmed = true;
}

void disarmMotorWatchdog() {
  motorWatchdogArmed = false;
}

void checkMotorWatchdog() {
  if (!motorWatchdogArmed) {
    return;
  }

  if (leftMotorPercent == 0 && rightMotorPercent == 0) {
    motorWatchdogArmed = false;
    return;
  }

  if (millis() - lastMotorCommandMs > MOTOR_WATCHDOG_TIMEOUT_MS) {
    Serial.println("WATCHDOG MOTEUR -> timeout, arret automatique.");
    stopMotors();
    motorWatchdogArmed = false;
  }
}

// =====================================================
// PAN-TILT
// =====================================================

void setPan(int value) {
  panPos = clampInt(value, PAN_MIN, PAN_MAX);
  panServo.write(panPos);

  Serial.print("PAN -> ");
  Serial.println(panPos);
}

void setTilt(int value) {
  int requested = value;

  tiltPos = clampInt(value, TILT_MIN, TILT_MAX);
  tiltServo.write(tiltPos);

  Serial.print("TILT -> ");
  Serial.print(tiltPos);

  if (requested < TILT_MIN) {
    Serial.print("  limite basse appliquee : ");
    Serial.print(TILT_MIN);
  }

  Serial.println();
}

void centerPanTilt() {
  Serial.println("Centrage pan-tilt...");
  setPan(90);
  delay(250);
  setTilt(90);
}

// =====================================================
// MOTEURS
// =====================================================

void motorWriteRaw(int pin, int pwm) {
  pwm = clampInt(pwm, 0, MOTOR_MAX_PWM);
  ledcWrite(pin, pwm);
}

void stopMotors() {
  motorWriteRaw(LEFT_FWD_PIN, 0);
  motorWriteRaw(LEFT_REV_PIN, 0);
  motorWriteRaw(RIGHT_FWD_PIN, 0);
  motorWriteRaw(RIGHT_REV_PIN, 0);

  leftMotorPercent = 0;
  rightMotorPercent = 0;
  disarmMotorWatchdog();

  Serial.println("MOTEURS -> STOP");
}

void setLeftMotor(int percent) {
  percent = clampInt(percent, -100, 100);
  int pwm = percentToPwm(abs(percent));

  if (percent > 0) {
    motorWriteRaw(LEFT_REV_PIN, 0);
    motorWriteRaw(LEFT_FWD_PIN, pwm);
  } else if (percent < 0) {
    motorWriteRaw(LEFT_FWD_PIN, 0);
    motorWriteRaw(LEFT_REV_PIN, pwm);
  } else {
    motorWriteRaw(LEFT_FWD_PIN, 0);
    motorWriteRaw(LEFT_REV_PIN, 0);
  }

  leftMotorPercent = percent;

  Serial.print("MOTEUR GAUCHE -> ");
  Serial.print(percent);
  Serial.println(" %");
}

void setRightMotor(int percent) {
  percent = clampInt(percent, -100, 100);
  int pwm = percentToPwm(abs(percent));

  if (percent > 0) {
    motorWriteRaw(RIGHT_REV_PIN, 0);
    motorWriteRaw(RIGHT_FWD_PIN, pwm);
  } else if (percent < 0) {
    motorWriteRaw(RIGHT_FWD_PIN, 0);
    motorWriteRaw(RIGHT_REV_PIN, pwm);
  } else {
    motorWriteRaw(RIGHT_FWD_PIN, 0);
    motorWriteRaw(RIGHT_REV_PIN, 0);
  }

  rightMotorPercent = percent;

  Serial.print("MOTEUR DROIT -> ");
  Serial.print(percent);
  Serial.println(" %");
}

void updateMotorWatchdogAfterCommand() {
  if (leftMotorPercent != 0 || rightMotorPercent != 0) {
    armMotorWatchdog();
  } else {
    disarmMotorWatchdog();
  }
}

void driveDirect(int leftPercent, int rightPercent) {
  leftPercent = clampInt(leftPercent, -100, 100);
  rightPercent = clampInt(rightPercent, -100, 100);

  Serial.print("DRIVE DIRECT -> G:");
  Serial.print(leftPercent);
  Serial.print(" %  D:");
  Serial.print(rightPercent);
  Serial.println(" %");

  setLeftMotor(leftPercent);
  setRightMotor(rightPercent);
  updateMotorWatchdogAfterCommand();
}

void driveForward(int percent) {
  percent = clampInt(percent, 0, 100);

  Serial.print("AVANCE -> ");
  Serial.print(percent);
  Serial.println(" %");

  setLeftMotor(percent);
  setRightMotor(percent);
  updateMotorWatchdogAfterCommand();
}

void driveBackward(int percent) {
  percent = clampInt(percent, 0, 100);

  Serial.print("RECUL -> ");
  Serial.print(percent);
  Serial.println(" %");

  setLeftMotor(-percent);
  setRightMotor(-percent);
  updateMotorWatchdogAfterCommand();
}

void turnLeft(int percent) {
  percent = clampInt(percent, 0, 100);

  Serial.print("TOURNE GAUCHE -> ");
  Serial.print(percent);
  Serial.println(" %");

  setLeftMotor(-percent);
  setRightMotor(percent);
  updateMotorWatchdogAfterCommand();
}

void turnRight(int percent) {
  percent = clampInt(percent, 0, 100);

  Serial.print("TOURNE DROITE -> ");
  Serial.print(percent);
  Serial.println(" %");

  setLeftMotor(percent);
  setRightMotor(-percent);
  updateMotorWatchdogAfterCommand();
}

void motorTest() {
  Serial.println("TEST MOTEURS COURT");
  Serial.println("IMPORTANT : RB2 doit etre sur cales.");

  stopMotors();
  delay(1000);

  driveForward(20);
  delay(700);

  stopMotors();
  delay(1000);

  driveBackward(20);
  delay(700);

  stopMotors();
  delay(1000);

  turnLeft(20);
  delay(700);

  stopMotors();
  delay(1000);

  turnRight(20);
  delay(700);

  stopMotors();

  Serial.println("TEST MOTEURS TERMINE");
}

// =====================================================
// ENCODEURS
// =====================================================

int8_t decodeQuadrature(uint8_t previous, uint8_t current) {
  if (previous == current) return 0;

  if ((previous == 0b00 && current == 0b01) ||
      (previous == 0b01 && current == 0b11) ||
      (previous == 0b11 && current == 0b10) ||
      (previous == 0b10 && current == 0b00)) {
    return 1;
  }

  if ((previous == 0b00 && current == 0b10) ||
      (previous == 0b10 && current == 0b11) ||
      (previous == 0b11 && current == 0b01) ||
      (previous == 0b01 && current == 0b00)) {
    return -1;
  }

  return 0;
}

uint8_t readEncoderState(int pinA, int pinB) {
  uint8_t a = digitalRead(pinA) ? 1 : 0;
  uint8_t b = digitalRead(pinB) ? 1 : 0;
  return (a << 1) | b;
}

void IRAM_ATTR updateFL() {
  uint8_t current = readEncoderState(ENC_FL_A, ENC_FL_B);
  int8_t delta = decodeQuadrature(lastFL, current);

  portENTER_CRITICAL_ISR(&encoderMux);
  encFL += delta;
  lastFL = current;
  portEXIT_CRITICAL_ISR(&encoderMux);
}

void IRAM_ATTR updateFR() {
  uint8_t current = readEncoderState(ENC_FR_A, ENC_FR_B);
  int8_t delta = decodeQuadrature(lastFR, current);

  portENTER_CRITICAL_ISR(&encoderMux);
  encFR += delta;
  lastFR = current;
  portEXIT_CRITICAL_ISR(&encoderMux);
}

void IRAM_ATTR updateRR() {
  uint8_t current = readEncoderState(ENC_RR_A, ENC_RR_B);
  int8_t delta = decodeQuadrature(lastRR, current);

  portENTER_CRITICAL_ISR(&encoderMux);
  encRR += delta;
  lastRR = current;
  portEXIT_CRITICAL_ISR(&encoderMux);
}

void IRAM_ATTR updateRL() {
  uint8_t current = readEncoderState(ENC_RL_A, ENC_RL_B);
  int8_t delta = decodeQuadrature(lastRL, current);

  portENTER_CRITICAL_ISR(&encoderMux);
  encRL += delta;
  lastRL = current;
  portEXIT_CRITICAL_ISR(&encoderMux);
}

void setupEncoders() {
  pinMode(ENC_FL_A, INPUT_PULLUP);
  pinMode(ENC_FL_B, INPUT_PULLUP);

  pinMode(ENC_FR_A, INPUT_PULLUP);
  pinMode(ENC_FR_B, INPUT_PULLUP);

  // GPIO34 et GPIO35 sont entrée seulement.
  // Ils n'ont pas de pull-up interne utilisable.
  pinMode(ENC_RR_A, INPUT);
  pinMode(ENC_RR_B, INPUT);

  pinMode(ENC_RL_A, INPUT_PULLUP);
  pinMode(ENC_RL_B, INPUT_PULLUP);

  lastFL = readEncoderState(ENC_FL_A, ENC_FL_B);
  lastFR = readEncoderState(ENC_FR_A, ENC_FR_B);
  lastRR = readEncoderState(ENC_RR_A, ENC_RR_B);
  lastRL = readEncoderState(ENC_RL_A, ENC_RL_B);

  attachInterrupt(digitalPinToInterrupt(ENC_FL_A), updateFL, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC_FL_B), updateFL, CHANGE);

  attachInterrupt(digitalPinToInterrupt(ENC_FR_A), updateFR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC_FR_B), updateFR, CHANGE);

  attachInterrupt(digitalPinToInterrupt(ENC_RR_A), updateRR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC_RR_B), updateRR, CHANGE);

  attachInterrupt(digitalPinToInterrupt(ENC_RL_A), updateRL, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC_RL_B), updateRL, CHANGE);

  Serial.println("Encodeurs initialises.");
}

void resetEncoders() {
  portENTER_CRITICAL(&encoderMux);
  encFL = 0;
  encFR = 0;
  encRR = 0;
  encRL = 0;
  portEXIT_CRITICAL(&encoderMux);

  Serial.println("Encodeurs remis a zero.");
}

void printEncoders() {
  long fl, fr, rr, rl;

  portENTER_CRITICAL(&encoderMux);
  fl = encFL;
  fr = encFR;
  rr = encRR;
  rl = encRL;
  portEXIT_CRITICAL(&encoderMux);

  Serial.println();
  Serial.println("===== ENCODEURS RB2 =====");
  Serial.print("Avant gauche   FL : ");
  Serial.println(fl);

  Serial.print("Avant droit    FR : ");
  Serial.println(fr);

  Serial.print("Arriere droit  RR : ");
  Serial.println(rr);

  Serial.print("Arriere gauche RL : ");
  Serial.println(rl);

  Serial.println("=========================");
  Serial.println();
}

// =====================================================
// AFFICHAGE
// =====================================================

void printHelp() {
  Serial.println();
  Serial.println("===== COMMANDES RB2 ESP32 =====");
  Serial.println("status      -> etat complet");
  Serial.println("help        -> aide");
  Serial.println();
  Serial.println("center      -> pan 90 / tilt 90");
  Serial.println("p90         -> pan a 90");
  Serial.println("p120        -> pan a 120");
  Serial.println("t90         -> tilt a 90");
  Serial.println("t68         -> tilt a 68");
  Serial.println("t40         -> tilt force a 68");
  Serial.println();
  Serial.println("stop        -> arret moteurs");
  Serial.println("f20         -> avance 20 %, arret auto apres 1 s si non repete");
  Serial.println("b20         -> recul 20 %, arret auto apres 1 s si non repete");
  Serial.println("l20         -> tourne gauche 20 %, arret auto apres 1 s si non repete");
  Serial.println("r20         -> tourne droite 20 %, arret auto apres 1 s si non repete");
  Serial.println();
  Serial.println("ml20        -> moteur gauche avance 20 %");
  Serial.println("mr20        -> moteur droit avance 20 %");
  Serial.println("gl20        -> moteur gauche recule 20 %");
  Serial.println("gr20        -> moteur droit recule 20 %");
  Serial.println();
  Serial.println("d20,20      -> commande directe gauche,droite");
  Serial.println("d-20,-20    -> recul direct");
  Serial.println("d-20,20     -> rotation gauche directe");
  Serial.println("d20,-20     -> rotation droite directe");
  Serial.println("d0,0        -> arret direct");
  Serial.println();
  Serial.println("enc         -> affiche encodeurs");
  Serial.println("encreset    -> reset encodeurs");
  Serial.println();
  Serial.println("mtest       -> test moteur court");
  Serial.println("===============================");
  Serial.println();
}

void printStatus() {
  Serial.println();
  Serial.println("===== RB2 ESP32 STATUS =====");

  Serial.print("PAN GPIO        : ");
  Serial.println(PAN_PIN);

  Serial.print("TILT GPIO       : ");
  Serial.println(TILT_PIN);

  Serial.print("PAN position    : ");
  Serial.println(panPos);

  Serial.print("TILT position   : ");
  Serial.println(tiltPos);

  Serial.print("TILT minimum    : ");
  Serial.println(TILT_MIN);

  Serial.print("LEFT FWD GPIO   : ");
  Serial.println(LEFT_FWD_PIN);

  Serial.print("LEFT REV GPIO   : ");
  Serial.println(LEFT_REV_PIN);

  Serial.print("RIGHT FWD GPIO  : ");
  Serial.println(RIGHT_FWD_PIN);

  Serial.print("RIGHT REV GPIO  : ");
  Serial.println(RIGHT_REV_PIN);

  Serial.print("Moteur gauche   : ");
  Serial.print(leftMotorPercent);
  Serial.println(" %");

  Serial.print("Moteur droit    : ");
  Serial.print(rightMotorPercent);
  Serial.println(" %");

  Serial.print("Watchdog moteur : ");
  Serial.println(motorWatchdogArmed ? "arme" : "inactif");

  Serial.print("Timeout moteur  : ");
  Serial.print(MOTOR_WATCHDOG_TIMEOUT_MS);
  Serial.println(" ms");

  Serial.println();
  Serial.println("Encodeurs GPIO :");

  Serial.print("FL A/B : ");
  Serial.print(ENC_FL_A);
  Serial.print("/");
  Serial.println(ENC_FL_B);

  Serial.print("FR A/B : ");
  Serial.print(ENC_FR_A);
  Serial.print("/");
  Serial.println(ENC_FR_B);

  Serial.print("RR A/B : ");
  Serial.print(ENC_RR_A);
  Serial.print("/");
  Serial.println(ENC_RR_B);

  Serial.print("RL A/B : ");
  Serial.print(ENC_RL_A);
  Serial.print("/");
  Serial.println(ENC_RL_B);

  printEncoders();

  Serial.print("Wi-Fi           : ");
  Serial.println(WiFi.status() == WL_CONNECTED ? "connecte" : "non connecte");

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("SSID            : ");
    Serial.println(ssid);

    Serial.print("Adresse IP      : ");
    Serial.println(WiFi.localIP());

    Serial.print("RSSI            : ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");

    Serial.print("Nom OTA         : ");
    Serial.println(otaHostname);
  }

  Serial.println("============================");
  Serial.println();
}

// =====================================================
// COMMANDE DIRECTE dG,D
// =====================================================

bool handleDirectDriveCommand(String cmd) {
  if (!cmd.startsWith("d")) return false;

  String payload = cmd.substring(1);
  int commaIndex = payload.indexOf(',');

  if (commaIndex < 0) {
    Serial.println("Commande d invalide. Format attendu : d20,20");
    return true;
  }

  String leftText = payload.substring(0, commaIndex);
  String rightText = payload.substring(commaIndex + 1);

  leftText.trim();
  rightText.trim();

  int leftValue = leftText.toInt();
  int rightValue = rightText.toInt();

  driveDirect(leftValue, rightValue);
  return true;
}

// =====================================================
// COMMANDES SERIE
// =====================================================

void handleCommand(String cmd) {
  cmd.trim();
  cmd.toLowerCase();

  if (cmd.length() == 0) return;

  if (otaActive) {
    stopMotors();
    Serial.println("OTA en cours. Commande ignoree.");
    return;
  }

  if (cmd == "help") {
    printHelp();
    return;
  }

  if (cmd == "status") {
    printStatus();
    return;
  }

  if (cmd == "enc") {
    printEncoders();
    return;
  }

  if (cmd == "encreset") {
    resetEncoders();
    return;
  }

  if (cmd == "center") {
    centerPanTilt();
    return;
  }

  if (cmd == "stop" || cmd == "s") {
    stopMotors();
    return;
  }

  if (cmd == "mtest") {
    motorTest();
    return;
  }

  if (handleDirectDriveCommand(cmd)) {
    return;
  }

  if (cmd.startsWith("ml")) {
    int value = cmd.substring(2).toInt();
    setLeftMotor(value);
    updateMotorWatchdogAfterCommand();
    return;
  }

  if (cmd.startsWith("mr")) {
    int value = cmd.substring(2).toInt();
    setRightMotor(value);
    updateMotorWatchdogAfterCommand();
    return;
  }

  if (cmd.startsWith("gl")) {
    int value = cmd.substring(2).toInt();
    setLeftMotor(-value);
    updateMotorWatchdogAfterCommand();
    return;
  }

  if (cmd.startsWith("gr")) {
    int value = cmd.substring(2).toInt();
    setRightMotor(-value);
    updateMotorWatchdogAfterCommand();
    return;
  }

  if (cmd.startsWith("p")) {
    int value = cmd.substring(1).toInt();
    setPan(value);
    return;
  }

  if (cmd.startsWith("t")) {
    int value = cmd.substring(1).toInt();
    setTilt(value);
    return;
  }

  if (cmd.startsWith("f")) {
    int value = cmd.substring(1).toInt();
    driveForward(value);
    return;
  }

  if (cmd.startsWith("b")) {
    int value = cmd.substring(1).toInt();
    driveBackward(value);
    return;
  }

  if (cmd.startsWith("l")) {
    int value = cmd.substring(1).toInt();
    turnLeft(value);
    return;
  }

  if (cmd.startsWith("r")) {
    int value = cmd.substring(1).toInt();
    turnRight(value);
    return;
  }

  Serial.print("Commande inconnue : ");
  Serial.println(cmd);
  printHelp();
}

void readSerial() {
  while (Serial.available() > 0) {
    char c = Serial.read();

    if (c == '\n' || c == '\r') {
      if (serialLine.length() > 0) {
        handleCommand(serialLine);
        serialLine = "";
      }
    } else {
      serialLine += c;
    }
  }
}

// =====================================================
// WIFI AVEC DIAGNOSTIC
// =====================================================

void setupWiFi() {
  Serial.println();
  Serial.println("Connexion Wi-Fi...");

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true);
  delay(500);

  Serial.println("Scan des reseaux Wi-Fi visibles...");
  int n = WiFi.scanNetworks();

  if (n == 0) {
    Serial.println("Aucun reseau Wi-Fi trouve.");
  } else {
    Serial.print(n);
    Serial.println(" reseaux trouves :");

    for (int i = 0; i < n; ++i) {
      Serial.print(i + 1);
      Serial.print(" : ");
      Serial.print(WiFi.SSID(i));
      Serial.print("  RSSI=");
      Serial.print(WiFi.RSSI(i));
      Serial.print(" dBm  Canal=");
      Serial.print(WiFi.channel(i));
      Serial.print("  Chiffrement=");
      Serial.println(WiFi.encryptionType(i));
      delay(10);
    }
  }

  Serial.println();
  Serial.print("Tentative connexion SSID : ");
  Serial.println(ssid);

  WiFi.begin(ssid, password);

  unsigned long startAttempt = millis();

  while (WiFi.status() != WL_CONNECTED && millis() - startAttempt < 30000) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    wifiOk = true;

    Serial.println("Wi-Fi connecte.");
    Serial.print("Adresse IP : ");
    Serial.println(WiFi.localIP());

    Serial.print("RSSI : ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
  } else {
    wifiOk = false;

    Serial.println("Wi-Fi NON connecte.");
    Serial.print("Code statut Wi-Fi : ");
    Serial.println(WiFi.status());

    Serial.println("OTA indisponible, mais serie USB active.");
  }
}

// =====================================================
// OTA
// =====================================================

void setupOTA() {
  if (!wifiOk) {
    Serial.println("OTA non demarre : Wi-Fi absent.");
    return;
  }

  ArduinoOTA.setHostname(otaHostname);
  ArduinoOTA.setPassword(otaPassword);

  ArduinoOTA.onStart([]() {
    otaActive = true;
    stopMotors();

    Serial.println();
    Serial.println("OTA demarre.");
    Serial.println("SECURITE : moteurs arretes.");
  });

  ArduinoOTA.onEnd([]() {
    stopMotors();

    Serial.println();
    Serial.println("OTA terminee. Redemarrage...");
  });

  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    Serial.printf("Progression OTA : %u%%\r", (progress * 100) / total);
  });

  ArduinoOTA.onError([](ota_error_t error) {
    stopMotors();

    Serial.println();
    Serial.print("Erreur OTA : ");
    Serial.println(error);

    if (error == OTA_AUTH_ERROR) {
      Serial.println("Erreur authentification.");
    } else if (error == OTA_BEGIN_ERROR) {
      Serial.println("Erreur debut OTA.");
    } else if (error == OTA_CONNECT_ERROR) {
      Serial.println("Erreur connexion OTA.");
    } else if (error == OTA_RECEIVE_ERROR) {
      Serial.println("Erreur reception OTA.");
    } else if (error == OTA_END_ERROR) {
      Serial.println("Erreur fin OTA.");
    }

    otaActive = false;
  });

  ArduinoOTA.begin();

  Serial.println("OTA pret.");
  Serial.print("Nom OTA : ");
  Serial.println(otaHostname);
  Serial.println("Mot de passe OTA : ****");
}

// =====================================================
// SETUP
// =====================================================

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("====================================================");
  Serial.println(" RB2 ESP32 - VERSION COMPLETE CORRIGEE ");
  Serial.println(" OTA + WIFI DIAGNOSTIC + PAN-TILT + MOTEURS + ENCODEURS ");
  Serial.println(" WATCHDOG MOTEUR 1000 ms ACTIF ");
  Serial.println("====================================================");

  // Pan-tilt
  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);

  panServo.setPeriodHertz(50);
  tiltServo.setPeriodHertz(50);

  panServo.attach(PAN_PIN, 500, 2500);
  tiltServo.attach(TILT_PIN, 500, 2500);

  delay(500);
  centerPanTilt();

  // Moteurs PWM
  ledcAttach(LEFT_FWD_PIN, MOTOR_PWM_FREQ, MOTOR_PWM_RES);
  ledcAttach(LEFT_REV_PIN, MOTOR_PWM_FREQ, MOTOR_PWM_RES);
  ledcAttach(RIGHT_FWD_PIN, MOTOR_PWM_FREQ, MOTOR_PWM_RES);
  ledcAttach(RIGHT_REV_PIN, MOTOR_PWM_FREQ, MOTOR_PWM_RES);

  stopMotors();

  // Encodeurs
  setupEncoders();
  resetEncoders();

  // Wi-Fi / OTA
  setupWiFi();
  setupOTA();

  printStatus();
  printHelp();

  Serial.println("Pret.");
}

// =====================================================
// LOOP
// =====================================================

void loop() {
  if (wifiOk) {
    ArduinoOTA.handle();
  }

  readSerial();
  checkMotorWatchdog();

  delay(5);
}