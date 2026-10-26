#include "telemetry_state.h"
#include <cassert>
#include <climits>
#include <iostream>

int main() {
  unoq::DeviceState state;
  state.boot = state.committed = state.upload = INT32_MAX;
  state.revision = state.sequence = state.milliseconds = state.command = UINT32_MAX;
  state.requested[0] = state.requested[1] = 7;
  state.pins[0] = state.pins[1] = -1; // widest readback representation: unavailable
  state.frame.fill(255);
  state.index = 31; state.count = 32;
  const auto snapshot = unoq::snapshotJson(state);
  assert(!snapshot.empty() && snapshot.size() <= 249);
  std::cout << snapshot << '\n';
  for (uint8_t kind : {unoq::RGB3, unoq::RGB4, unoq::MATRIX, unoq::ERROR}) {
    unoq::StateEvent event;
    event.state = state; event.token = INT32_MAX;
    event.kind = kind; event.cause = unoq::READBACK;
    event.error = -6; event.operation = 9;
    const auto encoded = unoq::eventJson(event);
    assert(!encoded.empty() && encoded.size() <= 215);
    std::cout << encoded << '\n';
  }
  auto copy = state;
  copy.milliseconds = 0; copy.sequence = 0; copy.revision = 0;
  assert(unoq::sameState(state, copy)); // timestamps/sequence do not fabricate a state change
  copy.frame[12] = 0;
  assert(!unoq::sameState(state, copy));
  copy = state; copy.pins[0] = 6;
  assert(!unoq::sameState(state, copy)); // actual readback changes independently of requests
  assert(unoq::rgbCause(copy, state, 0) == unoq::READBACK);
  copy.requested[0] = 3;
  assert(unoq::rgbCause(copy, state, 0) == unoq::COMMAND);
  copy.command = 0;
  assert(!unoq::matrixCommandChanged(copy, state, 1)); // RGB traffic cannot bypass matrix sampling
  assert(unoq::matrixCommandChanged(copy, state, 2));
}
