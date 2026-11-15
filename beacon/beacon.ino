// Echo Bluetooth beacon on a Seeed XIAO ESP32-S3 (CONTRACTS.md section 3, radio/nodes.json).
//
// The sketch drives the ESP32-S3's Bluetooth controller directly over its virtual HCI, with the same
// commands radio/hci.py uses on the scanner side (Bluetooth Core spec, Vol 4 Part E, 7.8). No host stack
// runs. Nothing here reads or prints the board's address, and the advert goes out from a random address
// made at each boot, so the board's own address is never on the air either.
//
// The beacon letter is picked at build time, for example the east beacon:
//   arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 --build-property "compiler.cpp.extra_flags=-DBEACON_ID='E'" beacon
// See beacon/README.md for flashing.

#include <esp_bt.h>
#include <esp_random.h>
#include <esp_task_wdt.h>

#ifndef BEACON_ID
#error "Set the beacon letter at build time, e.g. -DBEACON_ID='E' (see beacon/README.md)"
#endif
static_assert(BEACON_ID >= 'A' && BEACON_ID <= 'Z', "BEACON_ID must be one uppercase letter in quotes, like 'E'");
static_assert(BEACON_ID != 'S', "S is the Pi's beacon");

// Advertising every 35 ms (56 x 0.625 ms). On top of that the controller adds the spec's random
// advDelay of 0-10 ms to every event (Vol 6 Part B 4.4.2.2.1), so events come every 40 ms on average.
const uint16_t INTERVAL = 56;
const esp_power_level_t TX_POWER = ESP_PWR_LVL_P9;  // +9 dBm, fixed: never changed while running
const int TX_POWER_DBM = 9;

const uint32_t CHECK_EVERY_MS = 1000;  // ask the controller for a reply this often
const uint32_t REPORT_EVERY_CHECKS = 10;  // a status line on USB serial every 10 checks
const uint32_t WATCHDOG_MS = 5000;     // no reply for this long and the chip restarts
const uint32_t BLINK_EVERY_MS = 3000;  // one slow blink per period while advertising
const uint32_t BLINK_ON_MS = 200;
const uint8_t LED_ON = LOW, LED_OFF = HIGH;  // the XIAO's user LED (GPIO21) lights on LOW

// HCI opcodes (OGF << 10 | OCF)
const uint16_t HCI_RESET = 0x0C03;
const uint16_t LE_SET_RANDOM_ADDRESS = 0x2005;
const uint16_t LE_SET_ADV_PARAMS = 0x2006;
const uint16_t LE_READ_ADV_TX_POWER = 0x2007;
const uint16_t LE_SET_ADV_DATA = 0x2008;
const uint16_t LE_SET_ADV_ENABLE = 0x200A;

// LE Set Advertising Parameters (7.8.5)
const uint8_t ADV_PARAMS[15] = {
  INTERVAL & 0xFF, INTERVAL >> 8,  // Advertising_Interval_Min
  INTERVAL & 0xFF, INTERVAL >> 8,  // Advertising_Interval_Max, the same: a fixed interval
  0x03,                            // Advertising_Type: ADV_NONCONN_IND, legacy, non-connectable, undirected
  0x01,                            // Own_Address_Type: random (the one set in setup)
  0x00, 0, 0, 0, 0, 0, 0,          // Peer_Address_Type, Peer_Address: unused when undirected
  0x07,                            // Advertising_Channel_Map: 37, 38 and 39
  0x00,                            // Advertising_Filter_Policy: none
};

// LE Set Advertising Data (7.8.7): length, then 31 bytes. The data is byte for byte what the scanners
// keep (radio/tests/fixtures/hci/legacy_report_east.hex). No scan response: the scanners are passive.
const uint8_t ADV_DATA[32] = {
  10,                                              // Advertising_Data_Length
  0x02, 0x01, 0x06,                                // AD Flags: LE General Discoverable, no BR/EDR
  0x06, 0xFF, 0xFF, 0xFF, 0x52, 0x53, BEACON_ID,   // AD Manufacturer Specific Data: company FFFF, "R" "S", id
};

const uint8_t ENABLE[1] = {0x01};

// Each Command Complete from the controller as opcode << 16 | status << 8 | first return byte.
static QueueHandle_t replies;

// Called by the controller (from its own task) with each HCI packet for the host.
static int on_controller_packet(uint8_t *data, uint16_t len) {
  // 0x04 event packet, 0x0E Command Complete, length, Num_HCI_Command_Packets, Opcode (2), Status, return values
  if (len >= 7 && data[0] == 0x04 && data[1] == 0x0E) {
    uint32_t reply = uint32_t(data[4] | data[5] << 8) << 16 | data[6] << 8 | (len > 7 ? data[7] : 0);
    xQueueSend(replies, &reply, 0);
  }
  return 0;
}

static void on_send_available() {}

static const esp_vhci_host_callback_t callbacks = {on_send_available, on_controller_packet};

// Sends one HCI command and waits for its Command Complete. Returns the status, or -1 if no reply came.
// `ret` gets the first return parameter, if the command has one.
static int command(uint16_t opcode, const uint8_t *params = nullptr, uint8_t n = 0, uint8_t *ret = nullptr) {
  const uint32_t wait_ms = 500;
  uint8_t packet[4 + 32] = {0x01, uint8_t(opcode & 0xFF), uint8_t(opcode >> 8), n};
  if (n) memcpy(packet + 4, params, n);
  uint32_t start = millis();
  while (!esp_vhci_host_check_send_available()) {
    if (millis() - start > wait_ms) return -1;
    delay(1);
  }
  xQueueReset(replies);
  esp_vhci_host_send_packet(packet, 4 + n);
  uint32_t reply;
  while (xQueueReceive(replies, &reply, pdMS_TO_TICKS(wait_ms)) == pdTRUE) {
    if (reply >> 16 != opcode) continue;  // a late reply to an earlier command
    if (ret) *ret = reply & 0xFF;
    return reply >> 8 & 0xFF;
  }
  return -1;
}

static void must(bool ok, const char *step) {
  if (ok) return;
  Serial.printf("beacon %c: %s failed, restarting\n", BEACON_ID, step);
  Serial.flush();
  delay(100);
  esp_restart();
}

// Keep the Bluetooth controller's memory: the core frees it at boot unless a BLE library claims it.
extern "C" bool bleInUse(void) {
  return true;
}

static uint32_t advertising_since, last_reply;

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LED_OFF);
  Serial.begin(115200);

  // Watchdog: loop() has to feed it, and only does after the controller answers. Idle tasks are watched too.
  esp_task_wdt_config_t wdt = {.timeout_ms = WATCHDOG_MS, .idle_core_mask = 0b11, .trigger_panic = true};
  if (esp_task_wdt_reconfigure(&wdt) != ESP_OK) esp_task_wdt_init(&wdt);
  esp_task_wdt_add(NULL);

  replies = xQueueCreate(4, sizeof(uint32_t));
  must(btStart(), "Bluetooth controller start");
  must(esp_vhci_host_register_callback(&callbacks) == ESP_OK, "HCI callback");
  must(command(HCI_RESET) == 0, "HCI reset");
  uint8_t address[6];  // little-endian, so address[5] is the top byte
  esp_fill_random(address, sizeof address);  // true random: the radio is on
  address[5] |= 0xC0;  // a random static address has its two top bits set (Vol 6 Part B 1.3.2.1)
  must(command(LE_SET_RANDOM_ADDRESS, address, sizeof address) == 0, "random address");
  must(esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_ADV, TX_POWER) == ESP_OK, "TX power");
  must(esp_ble_tx_power_get(ESP_BLE_PWR_TYPE_ADV) == TX_POWER, "TX power read-back");
  must(command(LE_SET_ADV_PARAMS, ADV_PARAMS, sizeof ADV_PARAMS) == 0, "advertising parameters");
  must(command(LE_SET_ADV_DATA, ADV_DATA, sizeof ADV_DATA) == 0, "advertising data");
  must(command(LE_SET_ADV_ENABLE, ENABLE, sizeof ENABLE) == 0, "advertising enable");
  advertising_since = last_reply = millis();
  esp_task_wdt_reset();
}

void loop() {
  static uint32_t last_check, checks;
  uint32_t now = millis();
  if (now - last_check >= CHECK_EVERY_MS) {
    last_check = now;
    uint8_t dbm = 0;
    // Any reply, even an error status, shows the controller is still running.
    bool answered = command(LE_READ_ADV_TX_POWER, nullptr, 0, &dbm) >= 0;
    if (answered) {
      last_reply = millis();
      esp_task_wdt_reset();
    }
    if (checks++ % REPORT_EVERY_CHECKS == 0) {  // for arduino-cli monitor; nothing here identifies the board
      Serial.printf("beacon %c: advertising FFFF 52 53 %02X every %.3f ms at %+d dBm", BEACON_ID, BEACON_ID,
                    INTERVAL * 0.625, TX_POWER_DBM);
      if (answered) Serial.printf(" (controller reports %+d dBm)", int8_t(dbm));
      else Serial.print(" (controller not answering)");
      Serial.printf(", advertising since %lu ms after start, up %lu s%s\n", (unsigned long)advertising_since,
                    (unsigned long)(now / 1000), esp_reset_reason() == ESP_RST_TASK_WDT ? ", after a watchdog restart" : "");
    }
  }
  bool alive = millis() - last_reply < 2 * CHECK_EVERY_MS + 500;
  bool lit = alive && (now - advertising_since) % BLINK_EVERY_MS < BLINK_ON_MS;
  digitalWrite(LED_BUILTIN, lit ? LED_ON : LED_OFF);
  delay(10);
}
