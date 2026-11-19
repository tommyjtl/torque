"""Prepare per-map geometry, actor artwork and placement for DOOM1.WAD.

The index contains offsets into the original IWAD. No image or sound bytes are copied.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct
import os
import tempfile

SHA256 = "1d7d43be501e67d927e415e0b8f3e29c3bf33075e859721816f652a526cac771"


def atomic_write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        try:
            temp.write(data)
            temp.flush()
            os.fsync(temp.fileno())
            temp.close()
            os.replace(temp.name, path)
        finally:
            Path(temp.name).unlink(missing_ok=True)


def read_name(data):
    return data.rstrip(b"\0").decode("ascii").upper()


# Episode 1 behavior implemented in Hangar.activate, start_mover, shade and tick.
LINE_SPECIALS = {
    0,
    1,
    2,
    5,
    7,
    8,
    9,
    11,
    16,
    18,
    20,
    22,
    23,
    26,
    27,
    28,
    31,
    32,
    33,
    34,
    35,
    36,
    46,
    48,
    51,
    62,
    63,
    70,
    76,
    82,
    86,
    88,
    90,
    91,
    97,
    98,
    103,
}
SECTOR_SPECIALS = {0, 1, 2, 3, 4, 7, 8, 9, 11, 12, 13, 5, 16}


def check_specials(map_name, lump_name, records, field, supported):
    for record, fields in enumerate(records):
        special = fields[field]
        if special not in supported:
            raise ValueError(
                f"{map_name} {lump_name}[{record}] uses unsupported special {special}"
            )


def compile_index(path, map_name="E1M1", *, inventory=None):
    wad = path.read_bytes()
    if hashlib.sha256(wad).hexdigest() != SHA256:
        raise ValueError("Expected the original DOS DOOM shareware 1.9 IWAD.")
    if map_name not in {f"E1M{i}" for i in range(1, 10)}:
        raise ValueError("Choose an Episode 1 map from E1M1 through E1M9.")
    magic, count, directory = struct.unpack_from("<4sii", wad)
    entries = [
        (read_name(n), o, l) for o, l, n in struct.iter_unpack("<ii8s", wad[directory:])
    ]
    lumps = {n: (o, l) for n, o, l in entries}
    marker = next(i for i, item in enumerate(entries) if item[0] == map_name)
    map_lumps = {n: (o, l) for n, o, l in entries[marker + 1 : marker + 11]}

    def lump(n, table=lumps):
        o, l = table[n]
        return wad[o : o + l]

    def records(fmt, n):
        return list(struct.iter_unpack("<" + fmt, lump(n, map_lumps)))

    vertices = records("hh", "VERTEXES")
    lines = records("7H", "LINEDEFS")
    sides = records("hh8s8s8sH", "SIDEDEFS")
    secs = records("hh8s8shhh", "SECTORS")
    check_specials(map_name, "LINEDEFS", lines, 3, LINE_SPECIALS)
    check_specials(map_name, "SECTORS", secs, -2, SECTOR_SPECIALS)
    segs = records("6H", "SEGS")
    leaves = records("2H", "SSECTORS")
    nodes = records("12h2H", "NODES")
    pnames = lump("PNAMES")
    patches = [read_name(pnames[i : i + 8]) for i in range(4, len(pnames), 8)]
    textures = {}
    for tn in ("TEXTURE1", "TEXTURE2"):
        if tn not in lumps:
            continue
        data = lump(tn)
        num = struct.unpack_from("<I", data)[0]
        for off in struct.unpack_from("<" + "I" * num, data, 4):
            n, _, w, h, _, np = struct.unpack_from("<8sIhhIh", data, off)
            layers = []
            for j in range(np):
                x, y, k, _, _ = struct.unpack_from("<hhhhh", data, off + 22 + 10 * j)
                o, l = lumps[patches[k]]
                layers.append((x, y, o, l))
            textures[read_name(n)] = (w, h, layers)
    mats = []
    ids = {}
    layers = []

    def material(n, kind):
        n = read_name(n) if isinstance(n, bytes) else n
        if n == "-":
            return -1
        if (kind, n) in ids:
            return ids[kind, n]
        if kind == "flat" and n == "F_SKY1":
            return material("SKY1", "wall")
        if kind == "wall":
            w, h, parts = textures[n]
            flag = 0
        elif kind == "patch":
            o, l = lumps[n]
            w, h = struct.unpack_from("<hh", wad, o)
            parts = [(0, 0, o, l)]
            flag = 0
        else:
            o, l = lumps[n]
            assert l == 4096
            w = h = 64
            parts = [(0, 0, o, l)]
            flag = 1
        idx = len(mats)
        ids[kind, n] = idx
        mats.append((w, h, len(layers), len(parts), flag))
        layers.extend(parts)
        return idx

    # Convex subsector floors: intersect ancestor BSP half-planes and directed segs.
    def clip(poly, x, y, dx, dy, sign=1):
        out = []

        def distance(p):
            return sign * (dy * (p[0] - x) - dx * (p[1] - y))

        for a, b in zip(poly, poly[1:] + poly[:1]):
            da, db = distance(a), distance(b)
            if da >= -1e-6:
                out.append(a)
            if (da >= -1e-6) != (db >= -1e-6):
                t = da / (da - db)
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        return out

    tris = []
    triangle_lines = []

    # World z comes from an original sector floor or ceiling. UV coordinates in texels.
    def tri(mat, sec, verts, line=-1):
        if mat < 0:
            return
        triangle_lines.append(line)
        tris.append((mat, sec, *[v for vertex in verts for v in vertex]))

    def visit(index, poly):
        if index < 32768:
            x, y, dx, dy, *_ = nodes[index]
            for side, child in enumerate(nodes[index][-2:]):
                visit(child, clip(poly, x, y, dx, dy, 1 if side == 0 else -1))
            return
        num, first = leaves[index & 32767]
        group = segs[first : first + num]
        sec = sides[lines[group[0][3]][5 + group[0][4]]][-1]
        for a, b, *_ in group:
            x, y = vertices[a]
            bx, by = vertices[b]
            poly = clip(poly, x, y, bx - x, by - y)
        for i in range(1, len(poly) - 1):
            for ceiling in (0, 1):
                mat = material(secs[sec][2 + ceiling], "flat")
                tri(
                    mat,
                    sec,
                    [
                        (x, y, sec * 2 + ceiling, x, -y)
                        for x, y in (poly[0], poly[i], poly[i + 1])
                    ],
                )

    bounds = max(8192, max(abs(v) for vertex in vertices for v in vertex) + 1)
    visit(
        len(nodes) - 1,
        [(-bounds, -bounds), (bounds, -bounds), (bounds, bounds), (-bounds, bounds)],
    )
    # Both sides are generated. Floor/ceiling differences determine visible spans at runtime.
    for line_number, (a, b, flags, special, tag, front, back) in enumerate(lines):
        for side, opposite, v1, v2 in ((front, back, a, b), (back, front, b, a)):
            if side == 65535:
                continue
            xoff, yoff, upper, lower, middle, sec = sides[side]
            ax, ay = vertices[v1]
            bx, by = vertices[v2]
            length = math.hypot(bx - ax, by - ay)
            floor, ceil = sec * 2, sec * 2 + 1
            spans = []
            if opposite == 65535:
                spans = [(middle, floor, ceil, bool(flags & 16))]
            else:
                other = sides[opposite][-1]
                if not (secs[sec][3] == secs[other][3] == b"F_SKY1\0\0"):
                    spans.append((upper, other * 2 + 1, ceil, not bool(flags & 8)))
                spans.append((lower, floor, other * 2, bool(flags & 16)))
                if read_name(middle) != "-":
                    bottom = max((floor, other * 2), key=lambda k: secs[k // 2][k % 2])
                    top = min((ceil, other * 2 + 1), key=lambda k: secs[k // 2][k % 2])
                    spans.append((middle, bottom, top, bool(flags & 16)))
            for texture, lo, hi, peg_bottom in spans:
                mat = material(texture, "wall")
                if mat < 0:
                    continue
                # Negative anchor-encoding distinguishes wall UVs from flat UVs.
                anchor = lo if peg_bottom else hi
                # Encode linked height and vertical offset; renderer computes v from current z.
                code = (anchor + 1) * 8192 + 4096 + yoff
                verts = [
                    (ax, ay, lo, xoff, code),
                    (bx, by, lo, xoff + length, code),
                    (bx, by, hi, xoff + length, code),
                    (ax, ay, hi, xoff, code),
                ]
                tri(mat, sec, verts[:3], line_number)
                tri(mat, sec, [verts[0], verts[2], verts[3]], line_number)
    things = records("5h", "THINGS")
    names = {
        2028: "COLUA0",
        2035: "BAR1A0",
        2015: "BON2A0",
        2014: "BON1A0",
        9: "SPOSA1",
        3004: "POSSA1",
        3001: "TROOA1",
        2049: "SBOXA0",
        2048: "AMMOA0",
        2012: "MEDIA0",
        2008: "SHELA0",
        2046: "BROKA0",
        48: "ELECA0",
        2007: "CLIPA0",
        35: "CBRAA0",
        2011: "STIMA0",
        2018: "ARM1A0",
        2001: "SHOTA0",
        24: "POL5A0",
        2019: "ARM2A0",
        2003: "LAUNA0",
        2002: "MGUNA0",
        10: "PLAYW0",
        12: "PLAYW0",
        15: "PLAYN0",
    }
    names.update(
        {
            5: "BKEYA0",
            6: "YKEYA0",
            13: "RKEYA0",
            8: "BPAKA0",
            34: "CANDA0",
            46: "TREDA0",
            3002: "SARGA1",
            58: "SARGA1",
            3003: "BOSSA1",
            2005: "CSAWA0",
            2010: "ROCKA0",
            2013: "SOULA0",
            2024: "PINSA0",
            2025: "SUITA0",
            2026: "PMAPA0",
            2045: "PVISA0",
        }
    )
    species = {3004: 0, 9: 1, 3001: 2, 3002: 3, 58: 3, 3003: 4}
    sprites = []
    # Keep the actor IDs used by existing campaign saves. Newly supported blur
    # spheres occupy the tail of the table and preserve their original WAD order.
    for record, (x, y, angle, kind, flags) in sorted(
        enumerate(things), key=lambda item: item[1][3] == 2024
    ):
        if flags & 16 or kind in (1, 2, 3, 4, 11, 14):
            continue  # Starts and teleport destinations are read from THINGS at runtime.
        name = names.get(kind)
        if name not in lumps:
            raise ValueError(
                f"{map_name} THINGS[{record}] type {kind} has no sprite ({name})"
            )
        offset, _ = lumps[name]
        _, _, left, top = struct.unpack_from("<4h", wad, offset)
        sprites.append(
            (
                x,
                y,
                material(name, "patch"),
                left,
                top,
                kind,
                angle,
                flags,
                species.get(kind, -1),
            )
        )

    if ("patch", "PINSA0") in ids:
        for name in ("PINSB0", "PINSC0", "PINSD0"):
            material(name, "patch")

    # A rotation may be the mirrored second half of a patch name (e.g. A2A8).
    # Use four words per orientation: material, horizontal origin, top, mirror.
    rotation_records = []
    groups = ("POSS", "SPOS", "TROO", "SARG", "BOSS", "BAL1", "BAL7")
    needed = {row[-1] for row in sprites}
    if 2 in needed:
        needed.add(5)
    if 4 in needed:
        needed.add(6)
    for group, prefix in enumerate(groups):
        poses = {}
        if group in needed:
            for name, (offset, size) in lumps.items():
                if not name.startswith(prefix) or len(name) not in (6, 8):
                    continue
                for pos in range(4, len(name), 2):
                    letter, angle = name[pos : pos + 2]
                    if not "A" <= letter <= "O" or not angle.isdigit():
                        continue
                    width, _, left, top = struct.unpack_from("<4h", wad, offset)
                    mirror = int(pos == 6)
                    entry = (
                        material(name, "patch"),
                        width - left if mirror else left,
                        top,
                        mirror,
                    )
                    for view in range(8) if angle == "0" else [int(angle) - 1]:
                        poses[ord(letter) - 65, view] = entry
        for letter in range(15):
            for view in range(8):
                rotation_records.append(poses.get((letter, view), (-1, 0, 0, 0)))
    clip = material("CLIPA0", "patch")
    extra_sounds = [
        "DSPOSIT1",
        "DSBGSIT1",
        "DSPOPAIN",
        "DSPODTH1",
        "DSBGDTH1",
        "DSFIRSHT",
        "DSFIRXPL",
        "DSCLAW",
        "DSPLPAIN",
        "DSPLDETH",
        "DSSHOTGN",
        "DSSGTSIT",
        "DSSGTATK",
        "DSSGTDTH",
        "DSBRSSIT",
        "DSBRSDTH",
        "DSSAWFUL",
        "DSRLAUNC",
        "DSRXPLOD",
        "DSPUNCH",
        "DSWPNUP",
        "DSBAREXP",
    ]
    # Four entries per weapon: idle patch, two attack patches, muzzle flash.
    gun_names = [
        ("PUNGA0", "PUNGB0", "PUNGC0", None),
        ("PISGA0", "PISGB0", "PISGC0", "PISFA0"),
        ("SHTGA0", "SHTGB0", "SHTGC0", "SHTFA0"),
        ("CHGGA0", "CHGGB0", "CHGGA0", "CHGFA0"),
        ("MISGA0", "MISGB0", "MISGB0", "MISFA0"),
        ("SAWGA0", "SAWGC0", "SAWGD0", None),
    ]
    weapon_mats = [
        material(n, "patch") if n else -1 for frames in gun_names for n in frames
    ]
    misc_names = [
        "MISLA1",
        "MISLB0",
        "MISLC0",
        "MISLD0",
        "SHOTA0",
        "BEXPA0",
        "BEXPB0",
        "BEXPC0",
        "BEXPD0",
        "BEXPE0",
        "STKEYS0",
        "STKEYS1",
        "STKEYS2",
    ] + [f"STFST{i}0" for i in range(5)]
    misc_mats = [material(n, "patch") for n in misc_names]
    gun = [
        material(n, "patch") for n in ("PISGA0", "PISGB0", "PISFA0", "STBAR", "STFST00")
    ]
    digit_ids = [material("STTNUM" + str(i), "patch") for i in range(10)]
    digit_ids.append(material("STTPRCNT", "patch"))
    digit_ids.extend(material("STYSNUM" + str(i), "patch") for i in range(10))
    ui_names = (
        [
            "TITLEPIC",
            "M_DOOM",
            "M_NGAME",
            "M_LOADG",
            "M_SAVEG",
            "M_QUITG",
            "M_SKULL1",
            "M_SKULL2",
            "M_EPISOD",
            "M_EPI1",
            "M_SKILL",
            "M_JKILL",
            "M_ROUGH",
            "M_HURT",
            "M_ULTRA",
            "M_NMARE",
            "M_PAUSE",
            "WIMAP0",
            "WIF",
            "WIENTER",
            "WIOSTK",
            "WIOSTI",
            "WISCRT2",
            "WITIME",
            "WIPCNT",
            "WICOLON",
            "HELP2",
            "WIPAR",
        ]
        + [f"WINUM{i}" for i in range(10)]
        + [f"WILV0{i}" for i in range(9)]
    )
    # Runtime retains original map/sound references and decodes artwork from the IWAD.
    table_names = [
        "VERTEXES",
        "LINEDEFS",
        "SIDEDEFS",
        "SECTORS",
        "SEGS",
        "SSECTORS",
        "NODES",
        "THINGS",
        "PLAYPAL",
        "COLORMAP",
        "DSPISTOL",
        "DSDOROPN",
        "DSSWTCHN",
        "DSITEMUP",
    ]
    offsets = [
        v for n in table_names for v in (map_lumps if n in map_lumps else lumps)[n]
    ]

    def group(rows, fmt):
        return b"".join(struct.pack("<" + fmt, *r) for r in rows)

    sequences = {}
    for prefix, count in [
        ("NUKAGE", 3),
        ("FWATER", 4),
        ("SWATER", 4),
        ("LAVA", 4),
        ("BLOOD", 3),
        ("BLODGR", 4),
        ("SLADRIP", 3),
        ("BLODRIP", 4),
    ]:
        names = [prefix + str(i) for i in range(1, count + 1)]
        for kind in ("flat", "wall"):
            if not any((kind, n) in ids for n in names):
                continue
            available = lumps if kind == "flat" else textures
            if not all(n in available for n in names):
                continue
            frames = [material(n, kind) for n in names]
            for i, frame in enumerate(frames):
                sequences[frame] = frames[i:] + frames[:i]
    switches = {}
    for (kind, name), idx in list(ids.items()):
        if kind == "wall" and name.startswith(("SW1", "SW2")):
            other = ("SW2" if name.startswith("SW1") else "SW1") + name[3:]
            if other in textures:
                partner = material(other, kind)
                switches[idx] = partner
                switches[partner] = idx
    styles = []
    for mat in range(len(mats)):
        sequence = sequences.get(mat, [])
        styles.append(
            (switches.get(mat, -1), len(sequence), *(sequence + [-1] * 4)[:4])
        )
    order = sorted(range(len(tris)), key=lambda i: tris[i][0])
    header = struct.pack(
        "<4s32s4I28I5I",
        b"SYC3",
        hashlib.sha256(wad).digest(),
        len(mats),
        len(layers),
        len(tris),
        len(sprites),
        *offsets,
        *gun,
    )
    stops = []
    for sec, sector in enumerate(secs):
        neighbors = []
        for a, b, flags, special, tag, front, back in lines:
            if back == 65535:
                continue
            f, r = sides[front][-1], sides[back][-1]
            if f == sec and r != sec:
                neighbors.append(secs[r][1])
            if r == sec and f != sec:
                neighbors.append(secs[f][1])
        stops.append(max(0, min(neighbors, default=sector[1]) - 4 - sector[1]))

    def integers(values):
        values = list(values)
        return struct.pack("<" + "i" * len(values), *values)

    data = bytearray(
        header
        + group(mats, "5i")
        + group(layers, "4i")
        + group([tris[i] for i in order], "2i" + "ffiff" * 3)
        + group(sprites, "9i")
        + integers([*stops, *digit_ids, clip])
    )
    offsets = []
    sections = (
        group(rotation_records, "4i"),
        group([lumps[n] for n in extra_sounds], "2i"),
        integers(weapon_mats),
        integers(misc_mats),
        group(
            [
                lumps[n]
                for n in ("GENMIDI", "D_" + map_name, "D_INTER", "D_INTRO", "D_VICTOR")
            ],
            "2i",
        ),
        group([lumps[n] for n in ui_names], "2i"),
        group(styles, "6i"),
        integers(triangle_lines[i] for i in order),
        integers([ids.get(("wall", "SKY1"), -1)]),
        integers(ids["flat", read_name(sec[2])] for sec in secs),
    )
    for section in sections:
        offsets.append(len(data) // 4)
        data.extend(section)
    if inventory is not None:
        inventory[map_name] = {
            "single_player_thing_types": dict(
                sorted(
                    Counter(
                        kind for _, _, _, kind, flags in things if not flags & 16
                    ).items()
                )
            ),
            "medium_monsters": dict(
                sorted(
                    Counter(
                        kind
                        for _, _, _, kind, flags in things
                        if kind in species and flags & 2 and not flags & 16
                    ).items()
                )
            ),
            "line_specials": sorted({line[3] for line in lines if line[3]}),
            "sector_specials": sorted({sector[-2] for sector in secs if sector[-2]}),
            "exit_linedefs": [
                {"record": i, "special": line[3]}
                for i, line in enumerate(lines)
                if line[3] in (11, 51)
            ],
            "exit_sectors": [i for i, sector in enumerate(secs) if sector[-2] == 11],
            "sector_count": len(secs),
            "indexed_sprites": len(sprites),
            "materials": {
                kind: sorted(n for cat, n in ids if cat == kind)
                for kind in ("wall", "flat", "patch")
            },
            "sound_effects": table_names[10:] + extra_sounds,
            "music": ["D_" + map_name, "D_INTER", "D_INTRO", "D_VICTOR"],
        }
    data.extend(integers(offsets))
    return bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wad", type=Path)
    parser.add_argument(
        "--catalog",
        type=Path,
        help="Write native build fingerprints for the supported indexes",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        help="Write the per-map actor, asset, special and exit inventory as JSON",
    )
    args = parser.parse_args()
    inventory = {} if args.inventory else None
    entries = []
    for number in range(1, 10):
        name = f"E1M{number}"
        data = compile_index(args.wad, name, inventory=inventory)
        path = args.wad.with_suffix(".syi" if number == 1 else f".{name.lower()}.syi")
        atomic_write(path, data)
        digest = hashlib.sha256(data).hexdigest()
        header = struct.unpack_from("<46I", data)
        sectors = header[20] // 26
        lines = header[16] // 14
        state_words = 11 + sectors + 48 + 16 * header[12] + 11 * sectors + lines
        entries.append(
            f'    {{"{name}", {len(data)}, {state_words}, {sectors}, {header[12]}, "{digest}"}},'
        )
        print(name, path, len(data))
    if args.inventory:
        atomic_write(
            args.inventory,
            (
                json.dumps({"iwad_sha256": SHA256, "maps": inventory}, indent=2) + "\n"
            ).encode(),
        )
    if args.catalog:
        catalog = (
            "/* Generated from the verified DOOM shareware 1.9 IWAD. */\n"
            + "\n".join(entries)
            + "\n"
        )
        atomic_write(args.catalog, catalog.encode("ascii"))


if __name__ == "__main__":
    main()
