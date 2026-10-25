// Rogue AP / Evil Twin sensor (SSID/BSSID mismatch) - RMT Assignment 4
// ESP32, Arduino core. Only use with YOUR OWN test AP and a unique test SSID.
//
// Serial commands (115200 baud):
//   s <dwell_ms> <rogue|clean>  start a 60 s trial (e.g. "s 120 rogue")
//   m                           mark the moment the rogue AP was switched ON
// Log format (CSV-like lines, capture the terminal output to a .log file):
//   START,<trial_id>,<dwell_ms>,<rogue|clean>,<t_ms>
//   MARK,<t_ms>
//   HIT,<t_ms>,<channel>,<rssi>,<bssid>
//   END,<trial_id>,<t_ms>

#include <WiFi.h>
#include "esp_wifi.h"
#include "freertos/queue.h"

// ---- CONFIGURE THESE ----
const char*  TARGET_SSID = "RMT-TEST-AP";                       // unique test SSID
const uint8_t LEGIT_BSSID[6] = {0xAA, 0xBB, 0xCC, 0x11, 0x22, 0x33}; // BSSID of YOUR legit AP
const int    LED_PIN = 4;                                       // external red LED (+ resistor)
const int    MAX_CH = 13;
const uint32_t TRIAL_MS = 60000;
// -------------------------

struct Hit { uint32_t t; uint8_t ch; int8_t rssi; uint8_t bssid[6]; };
QueueHandle_t hitQ;

volatile bool trialActive = false;
uint32_t trialStart = 0, dwell = 120;
int trialId = 0, curCh = 1;
bool ledOn = false;

static void sniffer(void* buf, wifi_promiscuous_pkt_type_t type) {
  if (type != WIFI_PKT_MGMT || !trialActive) return;
  const wifi_promiscuous_pkt_t* p = (wifi_promiscuous_pkt_t*)buf;
  const uint8_t* d = p->payload;
  uint8_t fc = d[0];
  if (fc != 0x80 && fc != 0x50) return;          // beacon or probe response
  if (d[36] != 0) return;                        // first tag must be SSID (id 0)
  uint8_t len = d[37];
  if (len != strlen(TARGET_SSID) || len > 32) return;
  if (memcmp(&d[38], TARGET_SSID, len) != 0) return;
  const uint8_t* bssid = &d[16];                 // addr3 = BSSID
  if (memcmp(bssid, LEGIT_BSSID, 6) == 0) return; // legit AP -> ignore
  Hit h; h.t = millis(); h.ch = p->rx_ctrl.channel; h.rssi = p->rx_ctrl.rssi;
  memcpy(h.bssid, bssid, 6);
  xQueueSend(hitQ, &h, 0);
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  hitQ = xQueueCreate(32, sizeof(Hit));
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_promiscuous_rx_cb(&sniffer);
  wifi_promiscuous_filter_t f = { .filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT };
  esp_wifi_set_promiscuous_filter(&f);
  esp_wifi_set_promiscuous(true);
  Serial.println("READY. Use: s <dwell_ms> <rogue|clean>, then m when rogue is ON");
}

void handleSerial() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n'); line.trim();
  if (line.startsWith("s ")) {
    int sp = line.indexOf(' ', 2);
    dwell = line.substring(2, sp).toInt();
    String kind = line.substring(sp + 1);
    trialId++;
    digitalWrite(LED_PIN, LOW); ledOn = false;
    xQueueReset(hitQ);
    trialStart = millis();
    trialActive = true;
    Serial.printf("START,%d,%u,%s,%u\n", trialId, dwell, kind.c_str(), trialStart);
  } else if (line == "m" && trialActive) {
    Serial.printf("MARK,%u\n", millis());
  }
}

void loop() {
  handleSerial();
  if (trialActive) {
    curCh = (curCh % MAX_CH) + 1;                 // channel hopping 1..13
    esp_wifi_set_channel(curCh, WIFI_SECOND_CHAN_NONE);
    uint32_t until = millis() + dwell;
    while (millis() < until) {
      Hit h;
      while (xQueueReceive(hitQ, &h, 0) == pdTRUE) {
        if (!ledOn) { digitalWrite(LED_PIN, HIGH); ledOn = true; }  // red LED on first hit
        Serial.printf("HIT,%u,%u,%d,%02X:%02X:%02X:%02X:%02X:%02X\n", h.t, h.ch, h.rssi,
                      h.bssid[0], h.bssid[1], h.bssid[2], h.bssid[3], h.bssid[4], h.bssid[5]);
      }
      delay(1);
    }
    if (millis() - trialStart >= TRIAL_MS) {
      trialActive = false;
      Serial.printf("END,%d,%u\n", trialId, millis());
    }
  } else {
    delay(5);
  }
}
