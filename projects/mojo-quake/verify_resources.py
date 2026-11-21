"""Compare native Mojo decoders with independent reads of the private shareware PAK."""
from argparse import ArgumentParser
import ctypes as c
from pathlib import Path
import struct
import subprocess
import tempfile

from inspect_pak import pak_files


def wav_header(data):
    chunks = []
    at = 12
    while at + 8 <= len(data):
        name, size = struct.unpack_from("<4sI", data, at)
        chunks.append((name, at+8, size))
        at += 8 + size + (size & 1)
    begin, end = -1, 0
    for name, offset, size in chunks:
        if name == b"fmt ":
            fmt, channels, rate, _, _, bits = struct.unpack_from("<HHIIHH", data, offset)
            assert fmt == 1 and channels == 1
        elif name == b"data":
            pcm, pcm_bytes = offset, size
        elif name == b"cue ":
            begin, = struct.unpack_from("<I", data, offset+24)
        elif name == b"LIST" and begin >= 0 and data[offset+20:offset+24] == b"mark":
            length, = struct.unpack_from("<I", data, offset+16)
            end = begin + length
    width = bits // 8
    return rate, width, channels, begin, end or pcm_bytes//width, pcm


def check_wave(lib, raw):
    fields = (c.c_int * 6)()
    assert lib.mq_wave_info(raw, len(raw), fields)
    assert tuple(fields) == wav_header(raw)
    rate, width, _, _, frames, offset = fields
    # Compare signed sample conversion and nearest-source decimation together.
    for target_width in (1, 2):
        step = c.c_float(rate/16000).value
        length = int(c.c_float(frames/step).value)
        result = c.create_string_buffer(length * target_width)
        lib.mq_resample_pcm(raw[offset:], frames, width, result, length, target_width, step)
        source = memoryview(raw)[offset:]
        expected = bytearray()
        for i in range(length):
            index = min(int(c.c_float(i*step).value), frames-1)
            sample = ((source[index]-128)*256 if width == 1
                      else struct.unpack_from("<h", source, index*2)[0])
            if target_width == 1:
                expected.append((sample >> 8) & 255)
            else:
                expected.extend(struct.pack("<h", sample))
        assert result.raw == expected


def check_alias(lib, raw):
    skins, width, height, verts, triangles, frames = struct.unpack_from("<6i", raw, 48)
    offset = 84
    expanded_skins = 0
    for _ in range(skins):
        grouped, = struct.unpack_from("<i", raw, offset)
        offset += 4
        count = 1
        if grouped:
            count, = struct.unpack_from("<i", raw, offset)
            offset += 4+count*4
        expanded_skins += count
        offset += count * width * height
    texcoords = (c.c_int * (3*verts))()
    faces = (c.c_int * (4*triangles))()
    assert lib.mq_alias_mesh(raw[offset:], verts, triangles, texcoords, faces)
    assert bytes(texcoords) + bytes(faces) == raw[offset:offset+12*verts+16*triangles]
    offset += 12*verts + 16*triangles
    poses = 0
    for _ in range(frames):
        grouped, = struct.unpack_from("<i", raw, offset)
        offset += 4
        count = 1
        if grouped:
            count, = struct.unpack_from("<i", raw, offset)
            offset += 12+count*4
        poses += count
        offset += count * (24 + 4*verts)
    assert offset <= len(raw)
    counts = (c.c_int * 2)()
    assert lib.mq_alias_layout(raw, len(raw), counts)
    assert tuple(counts) == (expanded_skins, poses)


def check_visibility(lib, raw):
    sections = [raw[o:o+n] for o,n in struct.iter_unpack("<ii", raw[4:124])]
    compressed, leaves, models = sections[4], sections[10], sections[14]
    if not compressed:
        return 0
    leaf_count, = struct.unpack_from("<i", models, 52)
    row_bytes = (leaf_count+7)//8
    checked = 0
    for leaf in range(0, len(leaves), 28):
        start, = struct.unpack_from("<i", leaves, leaf+4)
        if start < 0:
            continue
        pos = start
        reference = bytearray()
        while len(reference) < row_bytes:
            value = compressed[pos]
            pos += 1
            if value:
                reference.append(value)
            else:
                reference.extend(bytes(compressed[pos]))
                pos += 1
        storage = (row_bytes+7) & ~7
        dest = c.create_string_buffer(storage)
        assert lib.mq_visibility_row(compressed[start:], len(compressed)-start, dest, storage, leaf_count)
        assert dest.raw == reference[:row_bytes]+bytes(storage-row_bytes)
        checked += 1
    return checked


def verify(obj, pak):
    with tempfile.TemporaryDirectory(prefix="mojo-quake-formats-") as scratch:
        shared = Path(scratch)/"resources.so"
        subprocess.run(["cc", "-shared", obj, "-o", shared], check=True)
        lib = c.CDLL(str(shared))
        ptr, number = c.c_void_p, c.c_int
        lib.mq_alias_layout.argtypes = [ptr, number, ptr]
        lib.mq_alias_mesh.argtypes = [ptr, number, number, ptr, ptr]
        lib.mq_wave_info.argtypes = [ptr, number, ptr]
        lib.mq_resample_pcm.argtypes = [ptr, number, number, ptr, number, number, c.c_float]
        lib.mq_resample_pcm.restype = None
        lib.mq_visibility_row.argtypes = [ptr, number, ptr, number, number]
        wavs = aliases = rows = 0
        for name, contents in pak_files(pak).items():
            if name.endswith(".mdl"):
                check_alias(lib, bytes(contents))
                aliases += 1
            elif name.endswith(".wav"):
                check_wave(lib, bytes(contents))
                wavs += 1
            elif name.endswith(".bsp"):
                rows += check_visibility(lib, bytes(contents))
        print(f"Matched {aliases} alias models, {wavs} PCM sounds and {rows} BSP visibility rows.")


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("native_object", type=Path)
    parser.add_argument("pak", type=Path)
    args = parser.parse_args()
    verify(args.native_object.resolve(), args.pak)
