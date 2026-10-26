#include "protocol.h"
#include "controller.h"
#include "telemetry.h"
#include <Arduino_LED_Matrix.h>
#include <Arduino_RouterBridge.h>
#include <zephyr/random/random.h>
#include <zephyr/drivers/gpio.h>
#include <cstdio>

static_assert(BRIDGE_RPC_BUFFER_SIZE >= 256, "base controller requires a 256-byte RPC buffer");

namespace {
constexpr const char* VERSION = "0.4.0";
unoq::Controller controller;
Arduino_LED_Matrix matrix;
uint8_t pixels[unoq::PIXELS]{};
int32_t bootId;
bool ready = false;
uint8_t requestedRgb[2]{};
const int ledPins[2][3] = {{LED3_R, LED3_G, LED3_B}, {LED4_R, LED4_G, LED4_B}};
const struct gpio_dt_spec rgbGpio[2][3] = {
  {GPIO_DT_SPEC_GET(DT_NODELABEL(led3_red), gpios), GPIO_DT_SPEC_GET(DT_NODELABEL(led3_green), gpios), GPIO_DT_SPEC_GET(DT_NODELABEL(led3_blue), gpios)},
  {GPIO_DT_SPEC_GET(DT_NODELABEL(led4_red), gpios), GPIO_DT_SPEC_GET(DT_NODELABEL(led4_green), gpios), GPIO_DT_SPEC_GET(DT_NODELABEL(led4_blue), gpios)}
};

void render() {
  if (controller.takeDirty()) {
    controller.unpack(pixels);
    matrix.draw(pixels);
  }
}

void captureState() {
  int8_t pins[2]{};
  for (int led = 0; led < 2; ++led) {
    for (int channel = 0; channel < 3; ++channel) {
      const auto& pin = rgbGpio[led][channel];
      // Raw electrical level, without gpio_dt_spec's possible active-low translation.
      int value = gpio_is_ready_dt(&pin) ? gpio_pin_get_raw(pin.port, pin.pin) : -1;
      if (value < 0) { pins[led] = -1; break; }
      if (value) pins[led] |= 1 << channel;
    }
  }
  unoq::telemetry::capture(controller, requestedRgb, pins);
}

int32_t result(uint8_t operation, int32_t code) {
  unoq::telemetry::command(operation, code);
  captureState();
  return code;
}

String info() {
  char out[128];
  std::snprintf(out, sizeof(out),
    "{\"name\":\"base-controller\",\"version\":\"%s\",\"protocol\":[1,3],\"boot_id\":%ld,\"ready\":%s}",
    VERSION, static_cast<long>(bootId), ready ? "true" : "false");
  return out;
}

String capability(String name) {
  if (name == "matrix")
    return "{\"rows\":8,\"columns\":13,\"max_frames\":32,\"min_duration_ms\":20,\"max_duration_ms\":60000,\"upload_timeout_ms\":30000,\"encoding\":\"bitset-hex-msb\"}";
  if (name == "rgb") return "{\"ids\":[3,4],\"binary\":true}";
  if (name == "matrix-presets") return "{\"max_presets\":9,\"max_frames\":32}";
  if (name == "matrix-grayscale")
    return "{\"rows\":8,\"columns\":13,\"max_frames\":32,\"min_duration_ms\":20,\"max_duration_ms\":60000,\"bits\":3,\"max_value\":7,\"encoding\":\"gray3-hex-msb\"}";
  if (name == "telemetry")
    return "{\"schema\":1,\"schemas\":[1,2],\"max_subscribers\":1,\"lease_ms\":10000,\"matrix_interval_ms\":200,\"queue_capacity\":8,\"rgb_source\":\"gpio_readback\",\"matrix_source\":\"firmware_framebuffer\"}";
  return "null";
}

String snapshot() { captureState(); return unoq::telemetry::snapshot(); }
String health() { captureState(); return unoq::telemetry::health(); }
int32_t subscribe(int32_t boot, String endpoint) {
  return boot != bootId ? unoq::STALE : unoq::telemetry::subscribe(endpoint);
}
int32_t renew(int32_t boot, int32_t token) {
  return boot != bootId ? unoq::STALE : unoq::telemetry::renew(token);
}
int32_t unsubscribe(int32_t boot, int32_t token) {
  return boot != bootId ? unoq::STALE : unoq::telemetry::unsubscribe(token);
}

String status() {
  char out[160];
  std::snprintf(out, sizeof(out),
    "{\"boot_id\":%ld,\"playing\":%s,\"frame\":%lu,\"frames\":%lu,\"upload_id\":%ld,\"committed_id\":%ld,\"preset\":%u}",
    static_cast<long>(bootId), controller.playing() ? "true" : "false",
    static_cast<unsigned long>(controller.frameIndex()), static_cast<unsigned long>(controller.frameCount()),
    static_cast<long>(controller.uploadId()), static_cast<long>(controller.committedId()), controller.preset());
  return out;
}

int32_t rgb(int32_t boot, int32_t led, bool r, bool g, bool b) {
  if (boot != bootId) return result(1, unoq::STALE);
  if (led != 3 && led != 4) return result(1, unoq::INVALID);
  const bool channels[3] = {r, g, b};
  for (int i = 0; i < 3; ++i) digitalWrite(ledPins[led - 3][i], channels[i] ? LOW : HIGH);
  requestedRgb[led - 3] = uint8_t(r) | (uint8_t(g) << 1) | (uint8_t(b) << 2);
  return result(1, unoq::OK);
}

int32_t draw(int32_t boot, String frame) {
  if (boot != bootId) return result(2, unoq::STALE);
  auto code = controller.draw(std::string(frame.c_str(), frame.length()));
  render();
  return result(2, code);
}
int32_t clear(int32_t boot) {
  if (boot != bootId) return result(3, unoq::STALE);
  controller.clear(); render(); return result(3, unoq::OK);
}
int32_t stop(int32_t boot) {
  if (boot != bootId) return result(4, unoq::STALE);
  controller.stop(); return result(4, unoq::OK);
}
int32_t begin(int32_t boot, int32_t count) {
  return result(5, boot != bootId ? unoq::STALE : controller.begin(count, millis()));
}
int32_t write(int32_t boot, int32_t id, int32_t index, String frame, int32_t duration) {
  return result(6, boot != bootId ? unoq::STALE : controller.write(id, index, std::string(frame.c_str(), frame.length()), duration, millis()));
}
int32_t commit(int32_t boot, int32_t id) {
  return result(7, boot != bootId ? unoq::STALE : controller.commit(id, millis()));
}
int32_t abortUpload(int32_t boot, int32_t id) {
  return result(8, boot != bootId ? unoq::STALE : controller.abort(id, millis()));
}
int32_t play(int32_t boot, int32_t repeat) {
  if (boot != bootId) return result(9, unoq::STALE);
  auto code = controller.play(repeat, millis());
  render(); return result(9, code);
}
int32_t drawGray(int32_t boot, String frame) {
  if (boot != bootId) return result(10, unoq::STALE);
  auto code = controller.draw(std::string(frame.c_str(), frame.length()), true);
  render(); return result(10, code);
}
int32_t beginGray(int32_t boot, int32_t count) {
  return result(11, boot != bootId ? unoq::STALE : controller.begin(count, millis(), true));
}
int32_t writeGray(int32_t boot, int32_t id, int32_t index, String frame, int32_t duration) {
  return result(12, boot != bootId ? unoq::STALE : controller.write(id, index,
    std::string(frame.c_str(), frame.length()), duration, millis(), true));
}
int32_t cache(int32_t boot, int32_t slot) {
  return result(13, boot != bootId ? unoq::STALE : controller.cache(slot));
}
int32_t playCached(int32_t boot, int32_t slot, int32_t repeat) {
  if (boot != bootId) return result(14, unoq::STALE);
  auto code = controller.playCached(slot, repeat, millis());
  render(); return result(14, code);
}
}  // namespace

void startController() {
  bootId = static_cast<int32_t>(sys_rand32_get() & 0x7fffffffU);
  if (!bootId) bootId = 1;
  for (const auto& led : ledPins)
    for (int pin : led) { pinMode(pin, OUTPUT); digitalWrite(pin, HIGH); }
  matrix.begin();
  matrix.setGrayscaleBits(3);
  matrix.clear();
  if (!Bridge.begin()) return;
  unoq::telemetry::start(bootId);
  captureState();
  // All callbacks and rendering execute in the Arduino main-loop thread.
  ready = true;
  ready = Bridge.provide_safe("unoq.control.v1.system.info", info) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.system.capability", capability) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.rgb.set", rgb) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.matrix.status", status) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.matrix.draw", draw) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.matrix.clear", clear) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.matrix.stop", stop) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.matrix.begin", begin) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.matrix.write_frame", write) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.matrix.commit", commit) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.matrix.abort", abortUpload) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.matrix.play", play) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.matrix.draw_gray", drawGray) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.matrix.begin_gray", beginGray) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.matrix.write_gray", writeGray) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.matrix.cache", cache) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.matrix.play_cached", playCached) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.system.snapshot", snapshot) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.system.health", health) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.system.subscribe", subscribe) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.system.renew", renew) && ready;
  ready = Bridge.provide_safe("unoq.control.v1.system.unsubscribe", unsubscribe) && ready;
}

void updateController() {
  controller.tick(millis());
  render();
  captureState();
  unoq::telemetry::publish();
}
