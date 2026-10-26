#pragma once

#include <array>
#include <cstdint>
#include <string>

namespace unoq {
constexpr uint32_t PIXELS = 104;
constexpr uint32_t MONO_BYTES = 13;
constexpr uint32_t FRAME_BYTES = 39;
constexpr uint32_t MAX_FRAMES = 32;
constexpr uint32_t MAX_PRESETS = 9;
constexpr uint32_t MIN_DURATION_MS = 20;
constexpr uint32_t MAX_DURATION_MS = 60000;
constexpr uint32_t UPLOAD_TIMEOUT_MS = 30000;
enum Result : int32_t { OK = 0, INVALID = -1, BUSY = -2, STALE = -3,
                        INCOMPLETE = -4, UNSUPPORTED = -5, NO_SPACE = -6 };
using Frame = std::array<uint8_t, FRAME_BYTES>;

// No Arduino dependencies: the exact playback and upload logic also runs in host tests.
class Controller {
 public:
  int32_t draw(const std::string& hex, bool grayscale = false);
  void clear();
  void stop();
  int32_t begin(int32_t count, uint32_t now, bool grayscale = false);
  int32_t write(int32_t id, int32_t index, const std::string& hex,
                int32_t duration, uint32_t now, bool grayscale = false);
  int32_t commit(int32_t id, uint32_t now);
  int32_t abort(int32_t id, uint32_t now);
  int32_t play(int32_t repeat, uint32_t now);
  int32_t cache(int32_t slot);
  int32_t playCached(int32_t slot, int32_t repeat, uint32_t now);
  void tick(uint32_t now);
  bool takeDirty();
  const Frame& frame() const { return visible_; }
  bool grayscale() const { return grayscale_; }
  bool playing() const { return playing_; }
  uint32_t frameIndex() const { return index_; }
  uint32_t frameCount() const { return playback().count; }
  uint8_t preset() const { return preset_; }
  int32_t uploadId() const { return pending_; }
  int32_t committedId() const { return committed_; }
  static bool decode(const std::string& hex, Frame& out);
  static bool decodeGray(const std::string& hex, Frame& out);
  static uint8_t pixel(const Frame& frame, uint32_t index) {
    uint8_t value = 0;
    for (uint32_t b = 0; b < 3; ++b) {
      const auto bit = index * 3 + b;
      value = (value << 1) | ((frame[bit / 8] >> (7 - bit % 8)) & 1);
    }
    return value;
  }
  void unpack(uint8_t* pixels) const;

 private:
  struct Animation {
    std::array<Frame, MAX_FRAMES> frames{};
    std::array<uint32_t, MAX_FRAMES> durations{};
    uint32_t count = 0;
    bool grayscale = false;
  };
  std::array<Animation, 2> banks_{};
  std::array<Animation, MAX_PRESETS> presets_{};
  Frame visible_{};
  uint32_t active_ = 0, index_ = 0, remaining_ = 0, shownAt_ = 0;
  uint32_t touchedAt_ = 0, written_ = 0;
  int32_t pending_ = 0, committed_ = 0, nextId_ = 0;
  bool dirty_ = true, playing_ = false;
  bool grayscale_ = false;
  uint8_t preset_ = 0;
  const Animation& playback() const { return preset_ ? presets_[preset_ - 1] : banks_[active_]; }
  int32_t startPlayback(int32_t repeat, uint32_t now, uint8_t preset);
  void expire(uint32_t now);
};
}  // namespace unoq
