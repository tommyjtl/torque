#include "telemetry_state.h"
#include <cstdio>

namespace unoq {
std::string frameHex(const Frame& frame) {
  const char* digits = "0123456789abcdef";
  std::array<uint8_t, MONO_BYTES> mono{};
  for (uint32_t i = 0; i < PIXELS; ++i)
    if (Controller::pixel(frame, i)) mono[i / 8] |= 1 << (7 - i % 8);
  std::string out(MONO_BYTES * 2, '0');
  for (uint32_t i = 0; i < MONO_BYTES; ++i) {
    out[i * 2] = digits[mono[i] >> 4];
    out[i * 2 + 1] = digits[mono[i] & 15];
  }
  return out;
}

std::string frameBase64(const Frame& frame) {
  const char* digits = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  std::string out;
  out.reserve(52);
  for (uint32_t i = 0; i < FRAME_BYTES; i += 3) {
    const uint32_t bits = (uint32_t(frame[i]) << 16) | (uint32_t(frame[i + 1]) << 8) | frame[i + 2];
    for (int shift = 18; shift >= 0; shift -= 6) out += digits[(bits >> shift) & 63];
  }
  return out;
}

namespace {
std::string matrixFields(const DeviceState& s) {
  char out[160];
  int n;
  if (s.grayscale) {
    n = std::snprintf(out, sizeof(out), ",\"m\":[\"%s\",%s,%lu,%lu,%ld,%ld]",
      frameBase64(s.frame).c_str(), s.playing ? "true" : "false",
      static_cast<unsigned long>(s.index), static_cast<unsigned long>(s.count),
      static_cast<long>(s.committed), static_cast<long>(s.upload));
  } else {
    n = std::snprintf(out, sizeof(out),
      ",\"f\":\"%s\",\"p\":%s,\"i\":%lu,\"n\":%lu,\"a\":%ld,\"u\":%ld",
      frameHex(s.frame).c_str(), s.playing ? "true" : "false", static_cast<unsigned long>(s.index),
      static_cast<unsigned long>(s.count), static_cast<long>(s.committed), static_cast<long>(s.upload));
  }
  if (n < 0 || n >= int(sizeof(out))) return {};
  if (s.preset) {
    const int extra = std::snprintf(out + n, sizeof(out) - n, ",\"j\":%u", s.preset);
    if (extra < 0 || extra >= int(sizeof(out) - n)) return {};
    n += extra;
  }
  return std::string(out, n);
}
}  // namespace

std::string snapshotJson(const DeviceState& s) {
  char out[224];
  int n = std::snprintf(out, sizeof(out),
    "{\"v\":%u,\"b\":%ld,\"s\":%lu,\"r\":%lu,\"t\":%lu,\"c\":%lu,\"rgb\":[[%u,%d],[%u,%d]]%s}",
    s.grayscale ? 2u : 1u, static_cast<long>(s.boot), static_cast<unsigned long>(s.sequence),
    static_cast<unsigned long>(s.revision), static_cast<unsigned long>(s.milliseconds),
    static_cast<unsigned long>(s.command), s.requested[0], s.pins[0], s.requested[1], s.pins[1],
    matrixFields(s).c_str());
  return n >= 0 && n < int(sizeof(out)) ? std::string(out, n) : std::string();
}

std::string eventJson(const StateEvent& e) {
  const auto& s = e.state;
  char out[216];
  const char* kind = e.kind == RGB3 ? "r3" : e.kind == RGB4 ? "r4" : e.kind == MATRIX ? "m" : "e";
  int n = std::snprintf(out, sizeof(out),
    "{\"v\":%u,\"b\":%ld,\"h\":%ld,\"s\":%lu,\"r\":%lu,\"t\":%lu,\"k\":\"%s\",\"c\":%lu,\"o\":%u",
    e.kind == MATRIX && s.grayscale ? 2u : 1u,
    static_cast<long>(s.boot), static_cast<long>(e.token), static_cast<unsigned long>(s.sequence),
    static_cast<unsigned long>(s.revision), static_cast<unsigned long>(s.milliseconds), kind,
    static_cast<unsigned long>(s.command), e.cause);
  if (n < 0 || n >= int(sizeof(out))) return {};
  int extra;
  if (e.kind == MATRIX) {
    extra = std::snprintf(out + n, sizeof(out) - n, "%s}", matrixFields(s).c_str());
  } else if (e.kind == ERROR) {
    extra = std::snprintf(out + n, sizeof(out) - n, ",\"e\":%ld,\"z\":%u}", static_cast<long>(e.error), e.operation);
  } else {
    const int led = e.kind == RGB3 ? 0 : 1;
    extra = std::snprintf(out + n, sizeof(out) - n, ",\"q\":%u,\"g\":%d}", s.requested[led], s.pins[led]);
  }
  return extra >= 0 && extra < int(sizeof(out) - n) ? std::string(out, n + extra) : std::string();
}

bool sameMatrix(const DeviceState& a, const DeviceState& b) {
  return a.frame == b.frame && a.preset == b.preset && a.grayscale == b.grayscale && a.playing == b.playing && a.index == b.index &&
         a.count == b.count && a.committed == b.committed && a.upload == b.upload;
}
bool sameState(const DeviceState& a, const DeviceState& b) {
  return sameMatrix(a, b) && a.command == b.command &&
         a.requested[0] == b.requested[0] && a.requested[1] == b.requested[1] &&
         a.pins[0] == b.pins[0] && a.pins[1] == b.pins[1];
}
bool matrixCommandChanged(const DeviceState& a, const DeviceState& b, uint8_t operation) {
  return a.command != b.command && operation >= 2 && operation <= 14;
}
uint8_t rgbCause(const DeviceState& a, const DeviceState& b, uint8_t led) {
  return a.requested[led] != b.requested[led] ? COMMAND : READBACK;
}
}  // namespace unoq
