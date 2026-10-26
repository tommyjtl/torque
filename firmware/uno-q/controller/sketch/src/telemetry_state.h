#pragma once
#include "controller.h"

namespace unoq {
struct DeviceState {
  int32_t boot = 0, committed = 0, upload = 0;
  uint32_t revision = 0, sequence = 0, milliseconds = 0, command = 0;
  uint8_t requested[2]{};
  int8_t pins[2]{};  // -1 means readback unavailable, not an assumed electrical level
  Frame frame{};
  uint32_t index = 0, count = 0;
  bool playing = false;
  bool grayscale = false;
  uint8_t preset = 0;
};
enum EventKind : uint8_t { RGB3 = 1, RGB4 = 2, MATRIX = 3, ERROR = 4 };
enum Cause : uint8_t { COMMAND = 0, PLAYBACK = 1, READBACK = 2 };
struct StateEvent {
  DeviceState state;
  int32_t token = 0, error = 0;
  uint8_t kind = 0, cause = 0, operation = 0;
};
std::string frameHex(const Frame& frame);
std::string frameBase64(const Frame& frame);
std::string snapshotJson(const DeviceState& state);
std::string eventJson(const StateEvent& event);
bool sameState(const DeviceState& a, const DeviceState& b);
bool sameMatrix(const DeviceState& a, const DeviceState& b);
bool matrixCommandChanged(const DeviceState& current, const DeviceState& previous, uint8_t operation);
uint8_t rgbCause(const DeviceState& current, const DeviceState& previous, uint8_t led);
}  // namespace unoq
