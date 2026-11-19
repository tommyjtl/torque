"""MUS event sequencer and two-operator FM synthesis using the IWAD's GENMIDI bank."""
from std.ffi import external_call
from std.math import max, min, sin
from std.memory import MutPointer
from std.origin import MutUntrackedOrigin

comptime Bytes = MutPointer[UInt8, MutUntrackedOrigin]
comptime Words = MutPointer[Int32, MutUntrackedOrigin]
comptime Floats = MutPointer[Float32, MutUntrackedOrigin]
comptime RATE = 22050
comptime VOICES = 18
comptime CHANNEL = 8
comptime VOICE = CHANNEL + 16 * 5


def byte(w: Bytes, k: Int) -> Int:
    return Int(w[unsafe_offset=k])


def small(w: Bytes, k: Int) -> Int:
    return byte(w, k) + 256 * byte(w, k + 1)


def mult(op: Int) -> Float32:
    var rate = op & 15
    if rate == 0:
        return 0.5
    if rate >= 14:
        return 15
    if rate >= 12:
        return 12
    if rate >= 10:
        return 10
    return Float32(rate)


@fieldwise_init
struct Sequencer(Copyable, Movable):
    var wad: Bytes
    var bank: Int
    var state: Words
    var synth: Floats
    var wave: Floats

    def get(self, k: Int) -> Int:
        return Int(self.state[unsafe_offset=k])

    def seek(self, song: Int, length: Int):
        if self.get(0) == 0:
            for i in range(2048):
                self.wave[unsafe_offset=i] = sin(Float32(i) * 0.0030679616)
        self.state[unsafe_offset=0] = Int32(song)
        self.state[unsafe_offset=1] = Int32(song + small(self.wad, song + 6))
        self.state[unsafe_offset=2] = self.state[unsafe_offset=1]
        self.state[unsafe_offset=3] = Int32(
            min(song + length, self.get(1) + small(self.wad, song + 4))
        )
        self.state[unsafe_offset=4] = 0
        self.state[unsafe_offset=5] = 0
        for ch in range(16):
            var c = CHANNEL + 5 * ch
            self.state[unsafe_offset=c] = 0
            self.state[unsafe_offset=c + 1] = 100
            self.state[unsafe_offset=c + 2] = 100
            self.state[unsafe_offset=c + 3] = 128
            self.state[unsafe_offset=c + 4] = 127
        for v in range(VOICES):
            self.state[unsafe_offset=VOICE + 3 * v] = 0

    def bend(self, v: Int, bend_value: Int):
        var f = v * 14
        var pitch = Float32(2.0) ** (Float32(bend_value - 128) / 768)
        self.synth[unsafe_offset=f + 2] = self.synth[unsafe_offset=f + 11] * pitch
        self.synth[unsafe_offset=f + 3] = self.synth[unsafe_offset=f + 12] * pitch

    def note(self, ch: Int, key: Int):
        var c = CHANNEL + 5 * ch
        var instrument = self.get(c)
        if ch == 15:
            if key < 35 or key > 81:
                return
            instrument = 128 + key - 35
        var preset = self.bank + 8 + 36 * instrument
        var v = self.get(5) % VOICES
        for n in range(VOICES):
            var j = (v + n) % VOICES
            if self.get(VOICE + 3 * j) == 0:
                v = j
                break
        self.state[unsafe_offset=5] = Int32(v + 1)
        var k = VOICE + 3 * v
        var f = 14 * v
        self.state[unsafe_offset=k] = Int32(ch + 1)
        self.state[unsafe_offset=k + 1] = Int32(key)
        self.state[unsafe_offset=k + 2] = 1
        var note_number = byte(self.wad, preset + 3) if small(self.wad, preset) & 1 else key + Int(
            Int16(UInt16(small(self.wad, preset + 18)))
        )
        var frequency = 440 * (Float32(2.0) ** (Float32(note_number - 69) / 12))
        var modulator = preset + 4
        var carrier = preset + 11
        for i in range(14):
            self.synth[unsafe_offset=f + i] = 0
        self.synth[unsafe_offset=f + 11] = min(
            Float32(1023), frequency * mult(byte(self.wad, carrier)) * 2048 / RATE
        )
        self.synth[unsafe_offset=f + 12] = min(
            Float32(1023), frequency * mult(byte(self.wad, modulator)) * 2048 / RATE
        )
        self.bend(v, self.get(c + 3))
        self.synth[unsafe_offset=f + 4] = (
            Float32(self.get(c + 1))
            / 127
            * (Float32(2) ** (-Float32(byte(self.wad, carrier + 5) & 63) / 8))
            * 0.10
        )
        var attack = byte(self.wad, carrier + 1) >> 4
        var decay = byte(self.wad, carrier + 1) & 15
        var sustain = byte(self.wad, carrier + 2) >> 4
        var release = byte(self.wad, carrier + 2) & 15
        self.synth[unsafe_offset=f + 6] = 1 / (
            Float32(RATE) * (0.003 + (Float32(2) ** (Float32(15 - attack) * 0.65)) * 0.003)
        )
        self.synth[unsafe_offset=f + 7] = 1 / (
            Float32(RATE) * (0.04 + (Float32(2) ** (Float32(15 - decay) * 0.55)) * 0.015)
        )
        self.synth[unsafe_offset=f + 8] = 0 if ch == 15 else Float32(2) ** (-Float32(sustain) / 2)
        self.synth[unsafe_offset=f + 9] = 1 / (
            Float32(RATE) * (0.018 + (Float32(2) ** (Float32(15 - release) * 0.55)) * 0.008)
        )
        self.synth[unsafe_offset=f + 10] = (
            Float32(2) ** (-Float32(byte(self.wad, modulator + 5) & 63) / 8) * 360
        )
        self.synth[unsafe_offset=f + 13] = Float32(byte(self.wad, modulator + 6) & 1)

    def event(self) -> Bool:
        var p = self.get(1)
        var end = self.get(3)
        if p >= end:
            return False
        var cmd = byte(self.wad, p)
        var kind = (cmd >> 4) & 7
        var ch = cmd & 15
        var c = CHANNEL + 5 * ch
        p += 1
        if kind == 6:
            return False
        if p >= end:
            return False
        var value = byte(self.wad, p)
        p += 1
        if kind == 0:
            for v in range(VOICES):
                var k = VOICE + 3 * v
                if self.get(k) == ch + 1 and self.get(k + 1) == value:
                    self.state[unsafe_offset=k + 2] = 3
        elif kind == 1:
            if value & 128:
                if p >= end:
                    return False
                self.state[unsafe_offset=c + 1] = Int32(byte(self.wad, p) & 127)
                p += 1
            self.note(ch, value & 127)
        elif kind == 2:
            self.state[unsafe_offset=c + 3] = Int32(value)
            for v in range(VOICES):
                if self.get(VOICE + 3 * v) == ch + 1:
                    self.bend(v, value)
        elif kind == 3 and value in (10, 11):
            for v in range(VOICES):
                if self.get(VOICE + 3 * v) == ch + 1:
                    self.state[unsafe_offset=VOICE + 3 * v + 2] = 3
        elif kind == 4:
            if p >= end:
                return False
            var control = byte(self.wad, p) & 127
            p += 1
            if value == 0:
                self.state[unsafe_offset=c] = Int32(control)
            elif value == 3:
                self.state[unsafe_offset=c + 2] = Int32(control)
            elif value == 5:
                self.state[unsafe_offset=c + 4] = Int32(control)
        if cmd & 128:
            var ticks = 0
            for _ in range(5):
                if p >= end:
                    return False
                var digit = byte(self.wad, p)
                p += 1
                ticks = min(90000, ticks * 128 + (digit & 127))
                if not (digit & 128):
                    break
            self.state[unsafe_offset=4] += Int32(ticks * RATE)
        self.state[unsafe_offset=1] = Int32(p)
        return True

    def mix(self, song: Int, length: Int, pcm: Floats, count: Int):
        if self.get(0) != song:
            self.seek(song, length)
        var cursor = 0
        while cursor < count:
            if self.get(4) <= 0:
                if not self.event():
                    self.seek(song, length)
                continue
            var span = min(count - cursor, (self.get(4) + 139) // 140)
            for v in range(VOICES):
                var k = VOICE + 3 * v
                var ch = self.get(k) - 1
                if ch < 0:
                    continue
                var f = v * 14
                var vol = (
                    Float32(self.get(CHANNEL + ch * 5 + 2) * self.get(CHANNEL + ch * 5 + 4))
                    / (127 * 127)
                    * self.synth[unsafe_offset=f + 4]
                )
                var env = self.synth[unsafe_offset=f + 5]
                var phase = self.synth[unsafe_offset=f]
                var mod_phase = self.synth[unsafe_offset=f + 1]
                var stage = self.get(k + 2)
                for i in range(span):
                    if stage == 1:
                        env += self.synth[unsafe_offset=f + 6]
                        if env >= 1:
                            env = 1
                            stage = 2
                    elif stage == 2:
                        env = max(
                            self.synth[unsafe_offset=f + 8], env - self.synth[unsafe_offset=f + 7]
                        )
                    else:
                        env -= self.synth[unsafe_offset=f + 9]
                        if env <= 0:
                            self.state[unsafe_offset=k] = 0
                            break
                    var op = self.wave[unsafe_offset=Int(mod_phase) & 2047]
                    var sample = self.wave[
                        unsafe_offset=Int(phase + op * self.synth[unsafe_offset=f + 10]) & 2047
                    ]
                    if self.synth[unsafe_offset=f + 13] > 0:
                        sample = (sample + op) * 0.5
                    pcm[unsafe_offset=cursor + i] += sample * env * vol
                    phase += self.synth[unsafe_offset=f + 2]
                    mod_phase += self.synth[unsafe_offset=f + 3]
                    if phase >= 2048:
                        phase -= 2048
                    if mod_phase >= 2048:
                        mod_phase -= 2048
                self.synth[unsafe_offset=f] = phase
                self.synth[unsafe_offset=f + 1] = mod_phase
                self.synth[unsafe_offset=f + 5] = env
                self.state[unsafe_offset=k + 2] = Int32(stage)
            self.state[unsafe_offset=4] -= Int32(span * 140)
            cursor += span
