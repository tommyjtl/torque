"""Binary resource decoding for Quake PAK, BSP and QuakeC. GPL-2.0-or-later."""
from qc import Bytes, Words, Floats
from snapshot import word


def fits(offset: Int, length: Int, size: Int) -> Bool:
    return 0 <= offset <= size and 0 <= length <= size - offset


@export("mq_pak_header")
def pak_header(data: Bytes, size: Int32, directory: Words) abi("C") -> Int32:
    if size < 12 or word(data, 0) != 0x4B434150:
        return -1
    var start = Int(word(data, 4))
    var length = Int(word(data, 8))
    if start < 12 or length % 64 or not fits(start, length, Int(size)):
        return -1
    directory[unsafe_offset=0] = Int32(start)
    return Int32(length // 64)


@export("mq_pak_entries")
def pak_entries(
    raw: Bytes,
    count: Int32,
    file_size: Int32,
    entries: Bytes,
    name_size: Int32,
) abi("C") -> Int32:
    var capacity = Int(name_size)
    for i in range(Int(count)):
        var src = i * 64
        var dst = i * (capacity + 8)
        var length = 0
        while length < 56 and raw[unsafe_offset=src + length]:
            length += 1
        if not length or length >= capacity:
            return 0
        for j in range(length):
            entries[unsafe_offset=dst + j] = raw[unsafe_offset=src + j]
        entries[unsafe_offset=dst + length] = 0
        var position = Int(word(raw, src + 56))
        var size = Int(word(raw, src + 60))
        if not fits(position, size, Int(file_size)):
            return 0
        for j in range(8):
            entries[unsafe_offset=dst + capacity + j] = raw[unsafe_offset=src + 56 + j]
    return 1


@export("mq_bsp_directory")
def bsp_directory(data: Bytes, file_size: Int32) abi("C") -> Int32:
    # A BSP starts with a version and fifteen offset/length pairs.
    if file_size < 124:
        return 0
    for i in range(15):
        var start = Int(word(data, 4 + 8 * i))
        var length = Int(word(data, 8 + 8 * i))
        if not fits(start, length, Int(file_size)) or (length and start < 124):
            return 0
        if not length:
            continue
        for j in range(i):
            var other = Int(word(data, 4 + 8 * j))
            var bytes = Int(word(data, 8 + 8 * j))
            if bytes and start < other + bytes and other < start + length:
                return 0
    return 1


@export("mq_qc_directory")
def qc_directory(data: Bytes, size: Int32) abi("C") -> Int32:
    if size < 60:
        return 0
    comptime widths = (8, 8, 8, 36, 1, 4)
    comptime for i in range(6):
        var start = Int(word(data, 8 + i * 8))
        var count = Int(word(data, 12 + i * 8))
        if start < 60 or not fits(start, count * widths[i], Int(size)):
            return 0
    return 1


@export("mq_vertices")
def vertices(src: Floats, target: Floats, count: Int32) abi("C"):
    for i in range(3 * Int(count)):
        target[unsafe_offset=i] = src[unsafe_offset=i]


@export("mq_planes")
def planes(
    src: Floats, raw: Bytes, out_values: Floats, out_info: Bytes, count: Int32
) abi("C") -> Int32:
    for i in range(Int(count)):
        var flags = 0
        for axis in range(4):
            var value = src[unsafe_offset=5 * i + axis]
            out_values[unsafe_offset=5 * i + axis] = value
            if axis < 3 and value < 0:
                flags |= 1 << axis
        var kind = Int(word(raw, 20 * i + 16))
        if kind > 5:
            return 0
        out_info[unsafe_offset=20 * i + 16] = UInt8(kind)
        out_info[unsafe_offset=20 * i + 17] = UInt8(flags)
    return 1


@export("mq_clipnodes")
def clipnodes(raw: Bytes, target: Words, count: Int32, plane_count: Int32) abi("C") -> Int32:
    for i in range(Int(count)):
        var plane = Int(word(raw, 8 * i))
        if plane >= Int(plane_count):
            return 0
        target[unsafe_offset=3 * i] = Int32(plane)
        for j in range(2):
            var byte = 8 * i + 4 + 2 * j
            var child = Int(raw[unsafe_offset=byte]) | (Int(raw[unsafe_offset=byte + 1]) << 8)
            if child > 0xFFF0:
                child -= 65536
            if child >= Int(count):
                return 0
            target[unsafe_offset=3 * i + 1 + j] = Int32(child)
    return 1


def little_short(data: Bytes, offset: Int) -> Int:
    return Int(data[unsafe_offset=offset]) | (Int(data[unsafe_offset=offset + 1]) << 8)


@export("mq_wave_info")
def wave_info(data: Bytes, size: Int32, info: Words) abi("C") -> Int32:
    """Read PCM format, data and the cue/LIST loop markers used by Quake."""
    if size < 12 or word(data, 0) != 0x46464952 or word(data, 8) != 0x45564157:
        return 0
    var end = 8 + Int(word(data, 4))
    if end < 12 or end > Int(size):
        return 0
    var rate = 0
    var channels = 0
    var width = 0
    var loop_start = -1
    var loop_end = 0
    var samples_offset = 0
    var samples_bytes = 0
    var pos = 12
    while pos + 8 <= end:
        var tag = word(data, pos)
        var length = Int(word(data, pos + 4))
        var body = pos + 8
        if not fits(body, length, end):
            # Some original WAVs end with a damaged editor annotation after a
            # complete PCM chunk. Never read past it or discard the valid audio.
            break
        if tag == 0x20746D66 and rate == 0:  # fmt
            if length < 16 or little_short(data, body) != 1:
                return 0
            channels = little_short(data, body + 2)
            rate = Int(word(data, body + 4))
            var bits = little_short(data, body + 14)
            if channels != 1 or rate < 1 or rate > 0x7FFFFFFF or (bits != 8 and bits != 16):
                return 0
            width = bits // 8
        elif tag == 0x61746164 and samples_offset == 0:  # data
            samples_offset = body
            samples_bytes = length
        elif tag == 0x20657563 and loop_start < 0:  # cue
            if length < 28:
                return 0
            loop_start = Int(word(data, body + 24))
        elif tag == 0x5453494C and length >= 24 and loop_start >= 0:  # LIST
            if word(data, body + 20) == 0x6B72616D:  # mark
                loop_end = loop_start + Int(word(data, body + 16))
        pos = body + length + (length & 1)
    if not width or not samples_offset:
        return 0
    var samples = samples_bytes // width
    if samples < 1 or loop_start >= samples or loop_end > samples:
        return 0
    info[unsafe_offset=0] = Int32(rate)
    info[unsafe_offset=1] = Int32(width)
    info[unsafe_offset=2] = Int32(channels)
    info[unsafe_offset=3] = Int32(loop_start)
    info[unsafe_offset=4] = Int32(loop_end if loop_end else samples)
    info[unsafe_offset=5] = Int32(samples_offset)
    return 1


@export("mq_resample_pcm")
def resample_pcm(
    source: Bytes,
    length: Int32,
    in_width: Int32,
    target: Bytes,
    out_count: Int32,
    out_width: Int32,
    step: Float32,
) abi("C"):
    for i in range(Int(out_count)):
        var j = min(Int(Float32(i) * step), Int(length) - 1)
        var sample: Int
        if in_width == 1:
            sample = (Int(source[unsafe_offset=j]) - 128) * 256
        else:
            sample = Int(Int16(UInt16(little_short(source, 2 * j))))
        if out_width == 1:
            target[unsafe_offset=i] = UInt8((sample >> 8) & 255)
        else:
            target[unsafe_offset=2 * i] = UInt8(sample & 255)
            target[unsafe_offset=2 * i + 1] = UInt8((sample >> 8) & 255)


@export("mq_alias_layout")
def alias_layout(raw: Bytes, size: Int32, counts: Words) abi("C") -> Int32:
    """Walk the grouped or single skins and poses in an IDPO version 6 model."""
    var end = Int(size)
    if end < 84 or word(raw, 0) != 0x4F504449 or word(raw, 4) != 6:
        return 0
    var skins = Int(word(raw, 48))
    var width = Int(word(raw, 52))
    var height = Int(word(raw, 56))
    var verts = Int(word(raw, 60))
    var triangles = Int(word(raw, 64))
    var frames = Int(word(raw, 68))
    if min(skins, width, height, verts, triangles, frames) < 1 or height > end // width:
        return 0
    var skin_bytes = width * height
    var pos = 84
    var skin_count = 0
    for _ in range(skins):
        if not fits(pos, 4, end):
            return 0
        var grouped = word(raw, pos) != 0
        pos += 4
        var n = 1
        if grouped:
            if not fits(pos, 4, end):
                return 0
            n = Int(word(raw, pos))
            pos += 4
            if not n or not fits(pos, 4 * n, end):
                return 0
            pos += 4 * n
        if n > (end - pos) // skin_bytes:
            return 0
        skin_count += n
        pos += n * skin_bytes
    if not fits(pos, 12 * verts + 16 * triangles, end):
        return 0
    pos += 12 * verts + 16 * triangles
    var pose_count = 0
    var pose_size = 24 + 4 * verts
    for _ in range(frames):
        if not fits(pos, 4, end):
            return 0
        var grouped = word(raw, pos) != 0
        pos += 4
        var n = 1
        if grouped:
            if not fits(pos, 12, end):
                return 0
            n = Int(word(raw, pos))
            pos += 12
            if not n or not fits(pos, 4 * n, end):
                return 0
            pos += 4 * n
        if n > (end - pos) // pose_size:
            return 0
        pose_count += n
        pos += n * pose_size
    counts[unsafe_offset=0] = Int32(skin_count)
    counts[unsafe_offset=1] = Int32(pose_count)
    return 1


@export("mq_alias_mesh")
def alias_mesh(
    raw: Bytes, verts: Int32, triangles: Int32, texcoords: Words, faces: Words
) abi("C") -> Int32:
    var words = 3 * Int(verts)
    for i in range(words):
        texcoords[unsafe_offset=i] = Int32(word(raw, i * 4))
    for i in range(Int(triangles)):
        var index = words + i * 4
        faces[unsafe_offset=4 * i] = Int32(word(raw, index * 4))
        for corner in range(1, 4):
            var v = Int(word(raw, 4 * (index + corner)))
            if v >= Int(verts):
                return 0
            faces[unsafe_offset=4 * i + corner] = Int32(v)
    return 1


@export("mq_visibility_row")
def visibility_row(
    encoded: Bytes, available: Int32, bits: Bytes, storage: Int32, leaves: Int32
) abi("C") -> Int32:
    """Expand the BSP potentially-visible-set row used by both scene backends."""
    var row = (Int(leaves) + 7) // 8
    if leaves < 0 or row > Int(storage):
        return 0
    for i in range(Int(storage)):
        bits[unsafe_offset=i] = 0
    var src = 0
    var dst = 0
    while dst < row:
        if src >= Int(available):
            return 0
        var value = encoded[unsafe_offset=src]
        src += 1
        if value:
            bits[unsafe_offset=dst] = value
            dst += 1
        else:
            if src >= Int(available):
                return 0
            var zeros = Int(encoded[unsafe_offset=src])
            if not zeros:
                return 0
            dst += zeros
            src += 1
    return 1
