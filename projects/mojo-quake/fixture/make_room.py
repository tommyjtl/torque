"""Build the original Torque movement room with ericw-tools 0.18.1."""
from argparse import ArgumentParser
from pathlib import Path
import struct
import subprocess
import tempfile


def brush(lo, hi, texture):
    x, y, z = lo
    X, Y, Z = hi
    planes = [
        [(x, y, z), (x, y, Z), (x, Y, z)],
        [(X, Y, Z), (X, y, Z), (X, Y, z)],
        [(x, y, z), (X, y, z), (x, y, Z)],
        [(X, Y, Z), (X, Y, z), (x, Y, Z)],
        [(x, y, z), (x, Y, z), (X, y, z)],
        [(X, Y, Z), (x, Y, Z), (X, y, Z)],
    ]
    # The map format uses clockwise points viewed from outside the solid.
    return "{\n" + "\n".join(" ".join("( %d %d %d )" % pt for pt in reversed(face))
                             + f" {texture} 0 0 0 1 1" for face in planes) + "\n}"


def room_map():
    solids = [
        ((-96, -96, -104), (592, 96, -72), "bedrock"),
        ((-96, -96, 160), (592, 96, 176), "ceiling"),
        ((-96, -96, -72), (-80, 96, 160), "wall"),
        ((576, -96, -72), (592, 96, 160), "wall"),
        ((-80, -96, -72), (576, -80, 160), "wall"),
        ((-80, 80, -72), (576, 96, 160), "wall"),
        ((-80, -80, -72), (64, 80, 0), "floor"),
        ((112, -80, -72), (224, 80, 32), "landing"),
        ((144, -80, 96), (200, 80, 160), "ceiling"),
        ((224, -80, -72), (400, 80, -12), "*pool"),
        ((400, -80, -72), (464, 80, -12), "*pool"),
        ((544, -80, -72), (576, 80, 0), "landing"),
    ]
    for i in range(3):
        solids.append(((64+16*i, -80, -72), (80+16*i, 80, 8*(i+1)), "step"))
    for i in range(9):
        solids.append(((400+16*i, -80, -72), (416+16*i, 80, -64+8*i), "step"))
    blocks = ['{\n"classname" "worldspawn"\n"message" "Torque movement room"\n"wad" "room.wad"']
    blocks.extend(brush(*solid) for solid in solids)
    blocks += ['}', '{\n"classname" "info_player_start"\n"origin" "0 0 32"\n"angle" "0"\n}']
    for x, z in [(16, 120), (154, 78), (260, 128), (364, 60), (514, 110)]:
        blocks.append(f'{{\n"classname" "light"\n"origin" "{x} 24 {z}"\n"light" "270"\n}}')
    return "\n".join(blocks) + "\n"


def materials():
    chunks, directory = bytearray(12), bytearray()
    for name, base in [('floor', 64), ('wall', 88), ('ceiling', 16), ('step', 108),
                       ('landing', 72), ('bedrock', 32), ('*pool', 200)]:
        label = name.encode().ljust(16, b'\0')
        levels, offsets = bytearray(), []
        for mip in range(4):
            offsets.append(40+len(levels))
            for y in range(32 >> mip):
                for x in range(32 >> mip):
                    u, v = x << mip, y << mip
                    pattern = (u//8 + v//8) % 2
                    levels.append(base + (0 if u == 0 or v == 0 else 3+3*pattern))
        lump = struct.pack('<16s6I', label, 32, 32, *offsets) + levels
        directory += struct.pack('<iiiBBBB16s', len(chunks), len(lump), len(lump), 68, 0, 0, 0, label)
        chunks += lump
    struct.pack_into('<4sii', chunks, 0, b'WAD2', len(directory)//32, len(chunks))
    return chunks + directory


def build(tools, destination):
    with tempfile.TemporaryDirectory() as scratch:
        directory = Path(scratch)
        (directory/'room.map').write_text(room_map())
        (directory/'room.wad').write_bytes(materials())
        for program in ['qbsp', 'vis', 'light']:
            subprocess.run([tools/program, 'room'], cwd=directory, check=True)
        destination.write_bytes((directory/'room.bsp').read_bytes())


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('tools', type=Path, help='directory containing qbsp, vis and light')
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    build(args.tools.resolve(), args.destination)
