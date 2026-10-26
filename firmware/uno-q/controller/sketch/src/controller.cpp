#include "controller.h"
#include <climits>

namespace unoq {
namespace {
bool decodeHex(const std::string& hex, uint8_t* out, uint32_t bytes) {
  if (hex.size() != bytes * 2) return false;
  for (uint32_t i = 0; i < hex.size(); ++i) {
    const char c = hex[i];
    int value = c >= '0' && c <= '9' ? c - '0' :
                c >= 'a' && c <= 'f' ? c - 'a' + 10 :
                c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
    if (value < 0) return false;
    out[i / 2] |= static_cast<uint8_t>(value << (i % 2 == 0 ? 4 : 0));
  }
  return true;
}
}  // namespace

bool Controller::decode(const std::string& hex, Frame& out) {
  std::array<uint8_t, MONO_BYTES> mono{};
  if (!decodeHex(hex, mono.data(), MONO_BYTES)) return false;
  Frame candidate{};
  for (uint32_t i = 0; i < PIXELS; ++i) {
    if (!(mono[i / 8] & (1 << (7 - i % 8)))) continue;
    for (uint32_t b = 0; b < 3; ++b) {
      const auto bit = i * 3 + b;
      candidate[bit / 8] |= 1 << (7 - bit % 8);
    }
  }
  out = candidate;
  return true;
}

bool Controller::decodeGray(const std::string& hex, Frame& out) {
  Frame candidate{};
  if (!decodeHex(hex, candidate.data(), FRAME_BYTES)) return false;
  out = candidate;
  return true;
}

int32_t Controller::draw(const std::string& hex, bool grayscale) {
  Frame candidate{};
  if (!(grayscale ? decodeGray(hex, candidate) : decode(hex, candidate))) return INVALID;
  visible_ = candidate;
  grayscale_ = grayscale;
  if (preset_) index_ = 0;
  preset_ = 0;
  playing_ = false;
  dirty_ = true;
  return OK;
}

void Controller::clear() {
  if (preset_) index_ = 0;
  preset_ = 0;
  playing_ = false;
  visible_.fill(0);
  grayscale_ = false;
  dirty_ = true;
}

void Controller::stop() { playing_ = false; }

void Controller::expire(uint32_t now) {
  if (pending_ && uint32_t(now - touchedAt_) >= UPLOAD_TIMEOUT_MS) {
    pending_ = 0;
    written_ = 0;
  }
}

int32_t Controller::begin(int32_t count, uint32_t now, bool grayscale) {
  expire(now);
  if (count < 1 || count > int32_t(MAX_FRAMES)) return INVALID;
  if (pending_) return BUSY;
  if (nextId_ == INT32_MAX) return NO_SPACE;
  banks_[1 - active_].count = count;
  banks_[1 - active_].grayscale = grayscale;
  written_ = 0;
  touchedAt_ = now;
  pending_ = ++nextId_;
  return pending_;
}

int32_t Controller::write(int32_t id, int32_t index, const std::string& hex,
                          int32_t duration, uint32_t now, bool grayscale) {
  expire(now);
  if (!pending_ || id != pending_) return STALE;
  auto& stage = banks_[1 - active_];
  if (stage.grayscale != grayscale) return INVALID;
  if (index < 0 || index >= int32_t(stage.count) ||
      duration < int32_t(MIN_DURATION_MS) || duration > int32_t(MAX_DURATION_MS)) return INVALID;
  Frame candidate{};
  if (!(grayscale ? decodeGray(hex, candidate) : decode(hex, candidate))) return INVALID;
  stage.frames[index] = candidate;
  stage.durations[index] = duration;
  written_ |= uint32_t(1) << index;
  touchedAt_ = now;
  return OK;
}

int32_t Controller::commit(int32_t id, uint32_t now) {
  expire(now);
  if (id > 0 && id == committed_) return OK;
  if (!pending_ || id != pending_) return STALE;
  const uint32_t count = banks_[1 - active_].count;
  const uint32_t complete = count == 32 ? UINT32_MAX : (uint32_t(1) << count) - 1;
  if (written_ != complete) return INCOMPLETE;
  active_ = 1 - active_;
  committed_ = pending_;
  pending_ = 0;
  written_ = 0;
  playing_ = false;
  index_ = 0;
  preset_ = 0;
  return OK;
}

int32_t Controller::abort(int32_t id, uint32_t now) {
  expire(now);
  if (!pending_ || id != pending_) return STALE;
  pending_ = 0;
  written_ = 0;
  return OK;
}

int32_t Controller::play(int32_t repeat, uint32_t now) {
  if (repeat < 0 || repeat > 65535) return INVALID;
  if (!committed_) return INCOMPLETE;
  return startPlayback(repeat, now, 0);
}

int32_t Controller::cache(int32_t slot) {
  if (slot < 1 || slot > int32_t(MAX_PRESETS)) return INVALID;
  if (!committed_) return INCOMPLETE;
  if (preset_ == slot) return BUSY;
  presets_[slot - 1] = banks_[active_];
  return OK;
}

int32_t Controller::playCached(int32_t slot, int32_t repeat, uint32_t now) {
  if (slot < 1 || slot > int32_t(MAX_PRESETS) || repeat < 0 || repeat > 65535) return INVALID;
  if (!presets_[slot - 1].count) return INCOMPLETE;
  return startPlayback(repeat, now, static_cast<uint8_t>(slot));
}

int32_t Controller::startPlayback(int32_t repeat, uint32_t now, uint8_t preset) {
  if (repeat < 0 || repeat > 65535) return INVALID;
  preset_ = preset;
  remaining_ = repeat;  // zero explicitly means continuous playback
  index_ = 0;
  visible_ = playback().frames[0];
  grayscale_ = playback().grayscale;
  shownAt_ = now;
  playing_ = dirty_ = true;
  return OK;
}

void Controller::tick(uint32_t now) {
  expire(now);
  if (!playing_) return;
  const auto& animation = playback();
  if (uint32_t(now - shownAt_) < animation.durations[index_]) return;
  if (index_ + 1 == animation.count) {
    if (remaining_ == 1) { playing_ = false; return; }
    if (remaining_ > 1) --remaining_;
    index_ = 0;
  } else {
    ++index_;
  }
  visible_ = animation.frames[index_];
  shownAt_ = now;  // late ticks hold frames; they do not produce a catch-up burst
  dirty_ = true;
}

bool Controller::takeDirty() {
  bool out = dirty_;
  dirty_ = false;
  return out;
}

void Controller::unpack(uint8_t* pixels) const {
  for (uint32_t i = 0; i < PIXELS; ++i)
    pixels[i] = pixel(visible_, i);
}
}  // namespace unoq
