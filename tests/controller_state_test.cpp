#include "controller.h"
#include <cassert>
#include <iostream>
using namespace unoq;

const std::string OFF(26, '0'), ON(26, 'f');

int main() {
  Controller c;
  uint8_t pixels[PIXELS]{};
  assert(c.draw("80040000000000000000000001") == OK);
  c.unpack(pixels);
  for (unsigned i = 0; i < PIXELS; ++i)
    assert(pixels[i] == (i == 0 || i == 13 || i == 103 ? 7 : 0));
  const auto before = c.frame();
  for (auto bad : {"", "0", "gggggggggggggggggggggggggg", "000000000000000000000000000"}) {
    assert(c.draw(bad) == INVALID);
    assert(c.frame() == before);
  }

  int id = c.begin(2, 0);
  assert(id > 0 && c.begin(1, 0) == BUSY);
  assert(c.commit(id, 0) == INCOMPLETE);
  assert(c.write(id, -1, OFF, 20, 0) == INVALID);
  assert(c.write(id, 2, OFF, 20, 0) == INVALID);
  assert(c.write(id, 0, OFF, 19, 0) == INVALID);
  assert(c.write(id, 0, OFF, 60001, 0) == INVALID);
  assert(c.write(id, 0, ON, 20, 0) == OK);
  assert(c.write(id, 0, OFF, 20, 0) == OK); // retry replaces a slot
  assert(c.commit(id, 0) == INCOMPLETE);
  assert(c.write(id, 1, ON, 20, 0) == OK);
  assert(c.commit(id, 0) == OK);
  assert(c.frame() == before); // committing does not display or start the animation
  assert(c.play(1, 100) == OK);
  c.tick(119);
  assert(c.frameIndex() == 0 && c.playing());
  c.tick(120);
  assert(c.frameIndex() == 1);
  c.tick(140);
  assert(!c.playing());
  c.unpack(pixels);
  for (auto pixel : pixels) assert(pixel == 7); // binary on retains full hardware brightness

  assert(c.play(0, 200) == OK);
  int replacement = c.begin(1, 200);
  assert(c.write(replacement, 0, "bad", 20, 200) == INVALID);
  assert(c.commit(replacement, 200) == INCOMPLETE);
  c.tick(220);
  assert(c.playing() && c.frameIndex() == 1); // partial upload cannot disrupt playback
  assert(c.commit(id, 220) == OK && c.playing()); // duplicate old commit has no effect
  assert(c.abort(replacement + 1, 220) == STALE);
  assert(c.abort(replacement, 220) == OK);
  c.tick(240);
  assert(c.playing() && c.frameIndex() == 0);
  const auto frame = c.frame();
  assert(c.draw("bad") == INVALID && c.playing() && c.frame() == frame);
  c.stop();
  assert(!c.playing() && c.frame() == frame);

  replacement = c.begin(1, 250);
  assert(c.write(replacement, 0, ON, 20, 250) == OK);
  assert(c.commit(replacement, 250) == OK && !c.playing());
  assert(c.frame() == frame);
  assert(c.play(2, UINT32_MAX - 10) == OK);
  c.tick(9); // 20 ms, including timer wrap
  assert(c.playing());
  c.tick(29);
  assert(!c.playing());

  id = c.begin(1, UINT32_MAX - 100);
  c.tick(29899); // exactly 30,000 ms after begin, including wrap
  assert(c.uploadId() == 0);
  assert(c.write(id, 0, ON, 20, 29899) == STALE);
  assert(c.committedId() == replacement);
  assert(c.play(-1, 0) == INVALID && c.play(65536, 0) == INVALID);

  id = c.begin(32, 0);
  for (int i = 0; i < 32; ++i) assert(c.write(id, i, i % 2 ? ON : OFF, 20, 0) == OK);
  assert(c.commit(id, 0) == OK && c.frameCount() == 32);
  assert(c.play(1, 0) == OK);
  for (uint32_t t = 20; t <= 640; t += 20) c.tick(t);
  assert(!c.playing() && c.frameIndex() == 31);
  c.clear();
  c.unpack(pixels);
  for (auto pixel : pixels) assert(pixel == 0);
  assert(sizeof(Controller) <= 16384); // active/staging storage plus nine resident clips
  std::cout << "controller state invariants passed\n";
}
