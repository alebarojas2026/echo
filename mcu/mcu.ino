// Echo LED matrix (8 x 13) on the UNO Q's microcontroller.
//
// Bridge functions, called from Linux:
//   show_zone(n)  0 = empty (a small dot), 1-4 = a big digit, -1 = "?" (no prediction)
//   alert(on)     true = blink an alert frame, false = stop
//   smile()       a smile for about 1.5 s, then back to what was showing
//
// The handlers run on the Bridge's own thread, so they only store the request
// and return. loop() does all the drawing.

#include <Arduino_LED_Matrix.h>
#include <Arduino_RouterBridge.h>

const int ROWS = 8;
const int COLS = 13;
const unsigned long SMILE_MS = 1500;
const unsigned long BLINK_MS = 300;

// Glyphs are 5 columns wide and 8 rows tall, one byte per row (bit 4 = left column).
const uint8_t DIGITS[5][ROWS] = {
  {0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000},  // 0 is the dot, drawn below
  {0b00110, 0b01110, 0b00110, 0b00110, 0b00110, 0b00110, 0b00110, 0b01111},  // 1
  {0b01110, 0b11011, 0b00011, 0b00011, 0b00110, 0b01100, 0b11000, 0b11111},  // 2
  {0b11110, 0b00011, 0b00011, 0b01110, 0b00011, 0b00011, 0b00011, 0b11110},  // 3
  {0b11011, 0b11011, 0b11011, 0b11111, 0b00011, 0b00011, 0b00011, 0b00011},  // 4
};
const uint8_t QUESTION[ROWS] = {0b01110, 0b11011, 0b00011, 0b00110, 0b00110, 0b00000, 0b00110, 0b00110};
const uint8_t BANG[ROWS] = {0b00000, 0b00110, 0b00110, 0b00110, 0b00110, 0b00000, 0b00110, 0b00000};

const uint8_t SMILE[ROWS * COLS] = {
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,1,1,0,0,0,1,1,0,0,0,
  0,0,0,1,1,0,0,0,1,1,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,1,0,0,0,0,0,0,0,0,0,1,0,
  0,0,1,0,0,0,0,0,0,0,1,0,0,
  0,0,0,1,1,1,1,1,1,1,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
};

Arduino_LED_Matrix matrix;

// Written by the Bridge thread, read by loop(). Single 32-bit values, so no locks.
volatile int32_t wanted_zone = -1;
volatile bool alert_on = false;
volatile uint32_t smile_requests = 0;

uint8_t frame[ROWS * COLS];
uint8_t shown[ROWS * COLS];
bool drawn_once = false;
uint32_t smiles_seen = 0;
unsigned long smile_started = 0;
bool smiling = false;

void show_zone(int32_t n) {
  wanted_zone = (n >= 0 && n <= 4) ? n : -1;
}

void alert(bool on) {
  alert_on = on;
}

void smile() {
  smile_requests = smile_requests + 1;
}

void clear_frame() {
  memset(frame, 0, sizeof(frame));
}

void put_glyph(const uint8_t glyph[ROWS], int left) {
  for (int r = 0; r < ROWS; r++) {
    for (int c = 0; c < 5; c++) {
      if (glyph[r] & (1 << (4 - c))) {
        frame[r * COLS + left + c] = 1;
      }
    }
  }
}

void put_zone(int32_t zone) {
  clear_frame();
  if (zone == 0) {
    frame[3 * COLS + 6] = frame[3 * COLS + 7] = 1;
    frame[4 * COLS + 6] = frame[4 * COLS + 7] = 1;
  } else if (zone >= 1 && zone <= 4) {
    put_glyph(DIGITS[zone], 4);
  } else {
    put_glyph(QUESTION, 4);
  }
}

void put_alert() {
  clear_frame();
  for (int c = 0; c < COLS; c++) {
    frame[c] = frame[(ROWS - 1) * COLS + c] = 1;
  }
  for (int r = 0; r < ROWS; r++) {
    frame[r * COLS] = frame[r * COLS + 1] = 1;
    frame[r * COLS + COLS - 2] = frame[r * COLS + COLS - 1] = 1;
  }
  put_glyph(BANG, 4);
}

void show_frame() {
  if (drawn_once && memcmp(frame, shown, sizeof(frame)) == 0) {
    return;
  }
  memcpy(shown, frame, sizeof(frame));
  matrix.draw(shown);
  drawn_once = true;
}

void setup() {
  matrix.begin();
  matrix.setGrayscaleBits(1);
  put_zone(-1);
  show_frame();

  Bridge.begin();
  Bridge.provide("show_zone", show_zone);
  Bridge.provide("alert", alert);
  Bridge.provide("smile", smile);
}

void loop() {
  unsigned long now = millis();

  uint32_t requests = smile_requests;
  if (requests != smiles_seen) {
    smiles_seen = requests;
    smile_started = now;
    smiling = true;
  }
  if (smiling && now - smile_started >= SMILE_MS) {
    smiling = false;
  }

  if (smiling) {
    memcpy(frame, SMILE, sizeof(frame));
  } else if (alert_on && (now / BLINK_MS) % 2 == 0) {
    put_alert();
  } else {
    put_zone(wanted_zone);
  }
  show_frame();
  delay(10);
}
