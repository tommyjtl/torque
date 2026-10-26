#include "controller.h"
#include "telemetry_state.h"
#include <cassert>
#include <climits>
#include <iostream>
using namespace unoq;

int32_t upload(Controller& c, const std::string& hex, bool gray, int count, uint32_t now) {
  auto id = c.begin(count, now, gray);
  assert(id > 0);
  for (int i = 0; i < count; ++i) assert(c.write(id, i, hex, 25, now, gray) == OK);
  assert(c.commit(id, now) == OK);
  return id;
}

int main() {
  Controller c;
  assert(c.cache(1) == INCOMPLETE && c.playCached(1, 0, 0) == INCOMPLETE);
  for (int bad : {-1, 0, 10}) {
    assert(c.cache(bad) == INVALID && c.playCached(bad, 0, 0) == INVALID);
  }
  assert(c.playCached(1, -1, 0) == INVALID);
  for (int slot = 1; slot <= 9; ++slot) {
    upload(c, std::string(78, char('0' + slot)), true, 32 - slot, 0);
    assert(c.cache(slot) == OK && !c.playing() && c.preset() == 0);
  }
  const auto committed = c.committedId();
  for (int slot = 1; slot <= 9; ++slot) {
    assert(c.playCached(slot, 0, 100) == OK);
    assert(c.frameCount() == uint32_t(32 - slot) && c.preset() == slot && c.grayscale());
    Frame expected{};
    assert(Controller::decodeGray(std::string(78, char('0' + slot)), expected));
    assert(c.frame() == expected && c.committedId() == committed);
    assert(c.cache(slot) == BUSY); // cannot overwrite selected storage
    const auto frame = c.frame();
    assert(c.playCached(slot, -1, 0) == INVALID && c.frame() == frame && c.playing());
  }
  c.stop();
  assert(c.preset() == 9 && c.cache(9) == BUSY);
  c.clear();
  assert(c.preset() == 0 && c.frameIndex() == 0 && c.cache(9) == OK);

  // A cached clip owns its storage while a normal upload is incomplete/expired.
  assert(c.playCached(1, 0, 0) == OK);
  const auto cached = c.frame();
  auto id = c.begin(32, 0, false);
  assert(c.write(id, 0, std::string(26, 'f'), 25, 0) == OK);
  assert(c.commit(id, 0) == INCOMPLETE && c.frame() == cached && c.playing());
  c.tick(30000);
  assert(c.uploadId() == 0 && c.preset() == 1 && c.playing());
  assert(c.commit(id, 30000) == STALE);

  // Commit preserves the held image, but ordinary play selects the new buffer.
  upload(c, std::string(26, 'f'), false, 1, 30000);
  assert(!c.playing() && c.preset() == 0 && c.frame() == cached && c.grayscale());
  assert(c.play(1, 30000) == OK && !c.grayscale() && c.frameCount() == 1);
  c.tick(30025); assert(!c.playing());
  assert(c.playCached(1, 1, UINT32_MAX - 10) == OK);
  for (uint32_t step = 1; step <= 31; ++step) c.tick(uint32_t(UINT32_MAX - 10 + step * 25));
  assert(!c.playing() && c.preset() == 1 && c.frameIndex() == 30);
  assert(c.draw(std::string(26, '0')) == OK && c.preset() == 0 && c.frameIndex() == 0);
  assert(c.playCached(1, 0, 0) == OK && c.grayscale()); // draw did not discard cache

  DeviceState s;
  s.boot = s.committed = s.upload = INT32_MAX;
  s.revision = s.sequence = s.milliseconds = s.command = UINT32_MAX;
  s.requested[0] = s.requested[1] = 7; s.pins[0] = s.pins[1] = -1;
  s.frame.fill(255); s.grayscale = true; s.preset = 9;
  s.index = 31; s.count = 32;
  std::cout << snapshotJson(s) << '\n';
  StateEvent e; e.state = s; e.token = INT32_MAX; e.kind = MATRIX; e.cause = COMMAND;
  auto event = eventJson(e);
  assert(!event.empty() && event.size() + 41 <= 256);
  std::cout << event << '\n';
  e.kind = ERROR; e.error = -2; e.operation = 14;
  std::cout << eventJson(e) << '\n';
  auto copy = s; copy.preset = 8;
  assert(!sameMatrix(s, copy));
  assert(sizeof(Controller) <= 16384);
  Controller reset;
  assert(reset.playCached(1, 0, 0) == INCOMPLETE);
}
