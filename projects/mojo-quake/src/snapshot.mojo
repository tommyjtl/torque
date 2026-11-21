"""Versioned gameplay snapshots for little-endian ARM64. GPL-2.0-or-later."""
from qc import Bytes
from std.ffi import external_call
from std.memory import MutPointer
from std.origin import MutUntrackedOrigin

# Each frame is a 32-bit byte count followed by its data. Frames need no alignment.
comptime META = 0
comptime GLOBALS = 1
comptime ENTITY = 2
comptime FIELDS = 3
comptime STRING = 4
comptime STYLE = 5
comptime MAGIC = 0x3153514D  # MQS1
comptime INTS = MutPointer[Int32, MutUntrackedOrigin]


def word(data: Bytes, offset: Int) -> UInt32:
    var value: UInt32 = 0
    for j in range(4):
        value |= UInt32(data[unsafe_offset=offset + j]) << UInt32(8 * j)
    return value


def put_word(data: Bytes, offset: Int, value: UInt32):
    for j in range(4):
        data[unsafe_offset=offset + j] = UInt8(value >> UInt32(8 * j))


@fieldwise_init
struct Stream:
    var data: Bytes
    var limit: Int
    var pos: Int
    var mode: Int  # 0 encode, 1 validate, 2 restore
    var layout: INTS

    def frame(mut self, kind: Int, index: Int, fixed: Int) -> Bool:
        if self.limit - self.pos < 4:
            return False
        var start = self.pos + 4
        var size: Int
        if self.mode == 0:
            var count: Int32 = 0
            var source = external_call["mq_snapshot_source", Bytes](
                Int32(kind), Int32(index), MutPointer(to=count)
            )
            size = Int(count)
            if size < 0 or size > self.limit - start:
                return False
            put_word(self.data, self.pos, UInt32(size))
            for j in range(size):
                self.data[unsafe_offset=start + j] = source[unsafe_offset=j]
        else:
            size = Int(word(self.data, self.pos))
            if size > self.limit - start:
                return False
        if fixed >= 0 and size != fixed:
            return False
        if kind == STRING or kind == STYLE:
            if size > 65536 or (kind == STRING and size == 0):
                return False
            if size and self.data[unsafe_offset=start + size - 1] != 0:
                return False
            for j in range(size - 1):
                if self.data[unsafe_offset=start + j] == 0:
                    return False
        if (
            self.mode != 0
            and external_call["mq_snapshot_receive", Int32](
                Int32(self.mode),
                Int32(kind),
                Int32(index),
                self.data.unsafe_offset(start),
                Int32(size),
                self.layout,
            )
            == 0
        ):
            return False
        self.pos = start + size
        return True


@export("mq_snapshot")
def snapshot(data: Bytes, capacity: Int32, layout: INTS, mode: Int32) abi("C") -> Int32:
    var size = Int(capacity)
    if size < 16 or size > (16 << 20):
        return 0
    if mode:
        if word(data, 0) != MAGIC or Int(word(data, 4)) != size:
            return 0
        var checksum = external_call["mq_hash", UInt32](
            data.unsafe_offset(12), Int32(size - 12), UInt32(2166136261)
        )
        if checksum != word(data, 8):
            return 0
    var s = Stream(data, size, 12, Int(mode), layout)
    if not s.frame(META, 0, Int(layout[unsafe_offset=0])):
        return 0
    var globals = Int(layout[unsafe_offset=1])
    var fields = Int(layout[unsafe_offset=2])
    var entities = Int(layout[unsafe_offset=3])
    var strings = Int(layout[unsafe_offset=4])
    if not (
        1 <= globals <= 65536
        and 1 <= fields <= 4096
        and 2 <= entities <= 8192
        and 0 <= strings <= 100000
    ):
        return 0
    if not s.frame(GLOBALS, 0, globals * 4):
        return 0
    for i in range(entities):
        if not s.frame(ENTITY, i, 16) or not s.frame(FIELDS, i, fields * 4):
            return 0
    for i in range(strings):
        if not s.frame(STRING, i, -1):
            return 0
    for i in range(64):
        if not s.frame(STYLE, i, -1):
            return 0
    if mode:
        return Int32(s.pos) if s.pos == size else 0
    put_word(data, 0, UInt32(MAGIC))
    put_word(data, 4, UInt32(s.pos))
    put_word(
        data,
        8,
        external_call["mq_hash", UInt32](
            data.unsafe_offset(12), Int32(s.pos - 12), UInt32(2166136261)
        ),
    )
    return Int32(s.pos)
