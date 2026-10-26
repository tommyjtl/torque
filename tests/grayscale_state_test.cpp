#include "controller.h"
#include "telemetry_state.h"
#include <cassert>
#include <climits>
#include <iostream>
using namespace unoq;

int main() {
  // 0..7 repeated: each eight pixels cross two byte boundaries, using 24 bits.
  std::string ramp;
  for (int i = 0; i < 13; ++i) ramp += "053977";
  Controller c;
  uint8_t pixels[PIXELS]{};
  assert(c.draw(ramp, true) == OK && c.grayscale());
  c.unpack(pixels);
  for (uint32_t i = 0; i < PIXELS; ++i) assert(pixels[i] == i % 8);
  const auto original = c.frame();
  Frame decoded{};
  assert(!Controller::decodeGray(ramp.substr(1), decoded));
  assert(!Controller::decodeGray(ramp + "0", decoded));
  assert(!Controller::decodeGray(std::string(78, 'g'), decoded));
  assert(c.draw(std::string(26, 'f'), true) == INVALID && c.frame() == original);
  assert(c.draw(ramp) == INVALID && c.grayscale());

  int id = c.begin(2, 0, true);
  assert(c.write(id, 0, std::string(26, 'f'), 20, 0) == INVALID);
  assert(c.commit(id, 0) == INCOMPLETE && c.frame() == original);
  assert(c.write(id, 0, std::string(78, '0'), 20, 0, true) == OK);
  assert(c.write(id, 1, ramp, 20, 0, true) == OK);
  assert(c.commit(id, 0) == OK && !c.playing() && c.frame() == original);
  assert(c.play(2, UINT32_MAX - 10) == OK && c.grayscale());
  c.tick(9);
  assert(c.frameIndex() == 1 && c.frame() == original);
  c.tick(29); c.tick(49); c.tick(69);
  assert(!c.playing() && c.frameIndex() == 1 && c.grayscale());

  // Replacing storage cannot reinterpret the currently visible format.
  id = c.begin(1, 100);
  assert(c.write(id, 0, ramp, 20, 100, true) == INVALID);
  assert(c.write(id, 0, std::string(26, 'f'), 20, 100) == OK);
  assert(c.commit(id, 100) == OK && c.grayscale() && c.frame() == original);
  assert(c.play(0, 100) == OK && !c.grayscale());
  c.unpack(pixels);
  for (auto p : pixels) assert(p == 7);
  id = c.begin(1, 100, true);
  assert(c.write(id, 0, ramp, 20, 100, true) == OK);
  c.tick(30100);
  assert(c.uploadId() == 0 && c.playing());
  assert(c.commit(id, 30100) == STALE && !c.grayscale());
  id = c.begin(32, 30100, true);
  for (int i = 0; i < 32; ++i) assert(c.write(id, i, ramp, 20, 30100, true) == OK);
  assert(c.commit(id, 30100) == OK && c.play(1, 30100) == OK);
  for (uint32_t t = 30120; t <= 30740; t += 20) c.tick(t);
  assert(!c.playing() && c.frameIndex() == 31 && c.frame() == original);
  c.stop();
  assert(c.grayscale() && c.frame() == original);

  DeviceState s;
  s.boot = s.committed = s.upload = INT32_MAX;
  s.revision = s.sequence = s.milliseconds = s.command = UINT32_MAX;
  s.requested[0] = s.requested[1] = 7;
  s.pins[0] = s.pins[1] = -1;
  s.frame = c.frame(); s.grayscale = c.grayscale();
  s.index = 31; s.count = 32;
  auto copy = s;
  copy.frame[0] ^= 1;  // brightness change without changing lit/off occupancy
  assert(!sameMatrix(s, copy));
  copy = s; copy.grayscale = false;
  assert(!sameMatrix(s, copy));
  copy = s; copy.command = 0;
  assert(matrixCommandChanged(s, copy, 10) && matrixCommandChanged(s, copy, 12));
  auto snapshot = snapshotJson(s);
  assert(!snapshot.empty() && snapshot.size() <= 249);
  std::cout << snapshot << '\n';
  StateEvent e;
  e.state = s; e.token = INT32_MAX; e.kind = MATRIX; e.cause = PLAYBACK;
  auto event = eventJson(e);
  assert(!event.empty() && event.size() <= 215);
  std::cout << event << '\n';
  // Full-brightness data exercises '+' and '/' Base64 alphabet entries too.
  e.state.frame.fill(255);
  std::cout << eventJson(e) << '\n';
  e.kind = ERROR; e.error = -1; e.operation = 12;
  std::cout << eventJson(e) << '\n';
  c.clear();
  assert(!c.grayscale());
  c.unpack(pixels);
  for (auto p : pixels) assert(p == 0);
  assert(sizeof(Controller) <= 16384);
}
