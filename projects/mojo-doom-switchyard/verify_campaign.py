"""Check campaign rules against an original local IWAD with isolated temporary saves."""

import argparse
import gzip
from collections import Counter
from pathlib import Path
import re
import struct
import subprocess
import tempfile


def checksum(data):
    result = 2166136261
    for value in data:
        result = (result ^ value) * 16777619 & 0xFFFFFFFF
    return result


def run_checks(executable, iwad, index, renderers=False):
    args = [str(executable), "--check", "--iwad", str(iwad), "--index", str(index)]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        trace = root / "commands.txt"
        slot = root / "test.sav"

        def play(commands, *options):
            trace.write_text(commands)
            p = subprocess.run(
                [*args, "--replay", str(trace), "--save", str(slot), *options],
                text=True,
                capture_output=True,
                timeout=25,
                check=True,
            )
            return dict(re.findall(r"(\w+)=([^\s]+)", p.stdout + p.stderr))

        def pose(seed, x, y, angle):
            modified = bytearray(seed)
            struct.pack_into("<3i", modified, 12, x * 256, y * 256, angle)
            struct.pack_into("<I", modified, len(modified) - 4, checksum(modified[:-4]))
            slot.write_bytes(modified)

        def index_layout(number):
            path = index if number == 1 else index.with_suffix(f".e1m{number}.syi")
            data = path.read_bytes()
            return struct.unpack(f"<{len(data)//4}i", data)

        def sprites_in(layout):
            start = 46 + 5 * layout[9] + 4 * layout[10] + 17 * layout[11]
            return [layout[i : i + 9] for i in range(start, start + 9 * layout[12], 9)]

        def payload():
            raw = slot.read_bytes()
            return struct.unpack(f"<{(len(raw)-16)//4}i", raw[12:-4])

        # Count actual THINGS records in each map independently of the renderer index.
        wad = iwad.read_bytes()
        directory_offset = struct.unpack_from("<I", wad, 8)[0]
        lumps = list(struct.iter_unpack("<II8s", wad[directory_offset:]))
        for number in range(1, 10):
            name = f"E1M{number}"
            marker = next(
                i
                for i, (_, _, tag) in enumerate(lumps)
                if tag.rstrip(b"\0").decode() == name
            )
            offset, size, _ = lumps[marker + 1]
            things = list(struct.iter_unpack("<5h", wad[offset : offset + size]))
            layout = index_layout(number)
            indexed = Counter(
                (x, y, angle, kind, flags)
                for x, y, _, _, _, kind, angle, flags, _ in sprites_in(layout)
            )
            for record, thing in enumerate(things):
                if thing[3] in (1, 2, 3, 4, 11, 14) or thing[4] & 16:
                    continue
                assert indexed[thing] > 0, (
                    name,
                    "missing THINGS record",
                    record,
                    thing,
                )
                indexed[thing] -= 1
            assert not +indexed, (name, "extra sprites", +indexed)
            for skill, mask in ((1, 1), (3, 2), (4, 4)):
                kinds = Counter(
                    kind
                    for _, _, _, kind, flags in things
                    if flags & mask and not flags & 16
                )
                expected = sum(kinds[t] for t in (3004, 9, 3001, 3002, 58, 3003))
                result = play("1 0 0 0 0\n", "--map", name, "--skill", str(skill))
                assert int(result["living"]) == expected, (name, skill, result)
        print("Verified original easy, medium and hard spawns across all nine maps.")

        print(
            "Verified every single-player thing's type, coordinates, facing and flags against the IWAD."
        )
        route = Path(__file__).parent / "evidence/e1m1-encounter.trace"
        encounter = play(route.read_text())
        assert int(encounter["kills"]) >= 1 and int(encounter["health"]) > 0, encounter
        print(
            "Walked from the real player start, opened the door and won the first firefight."
        )

        play("1 0 0 0 4\n")
        baseline = slot.read_bytes()
        legacy = root / "original-hangar.sav"
        data = bytearray(baseline[: 12 + 96 * 4])
        struct.pack_into("<I", data, 4, 1)
        struct.pack_into("<i", data, 12 + 5 * 4, 33)
        data.extend(struct.pack("<I", checksum(data)))
        legacy.write_bytes(data)
        imported = play("1 0 0 0 4\n", "--import-hangar", str(legacy))
        assert imported["ammo"] == "33" and imported["living"] == "6"
        assert legacy.read_bytes() == data
        broken = bytearray(slot.read_bytes())
        broken[-1] ^= 1
        slot.write_bytes(broken)
        failed = subprocess.run(
            [*args, "--resume", "--save", slot], capture_output=True
        )
        assert failed.returncode == 3 and slot.read_bytes() == broken
        print(
            "Imported a Hangar checkpoint into a separate slot and rejected a corrupt campaign save."
        )
        # Both shots are 64 map units from the same original zombieman.
        layout = index_layout(1)
        enemy = next(
            i
            for i, row in enumerate(sprites_in(layout))
            if row[:2] == (2272, -2432) and row[5] == 3004 and row[7] & 2
        )
        enemy_hp = 11 + layout[20] // 26 + 48 + 16 * enemy + 2
        for x, angle, behind_wall in ((2336, 2048, True), (2208, 0, False)):
            pose(baseline, x, -2432, angle)
            result = play("1 0 0 0 1\n1 0 0 0 4\n", "--resume")
            assert result["ammo"] == "49"
            hp = payload()[enemy_hp]
            assert hp == 20 if behind_wall else hp < 20
        print(
            "Hangar linedef 406 blocks a pistol shot. The same target takes damage in the open."
        )

        for skill, expected_ammo in ((1, 70), (3, 60), (5, 70)):
            play("1 0 0 0 4\n", "--skill", str(skill))
            pose(slot.read_bytes(), 2736, -4160, 0)
            assert play("1 0 0 0 0\n", "--resume")["ammo"] == str(expected_ammo)
        print("Clip pickup grants 10 bullets on medium and 20 on ITYTD and Nightmare.")

        # Exercise the same corpse and respawn roll on both difficulty settings.
        player = 11 + layout[20] // 26
        imp_index = next(
            i
            for i, thing in enumerate(sprites_in(layout))
            if thing[:2] == (3440, -3472) and thing[5] == 3001
        )
        actor = player + 48 + 16 * imp_index
        for skill, expected_hp in ((3, 0), (5, 60)):
            play("1 0 0 0 4\n", "--skill", str(skill))
            seed = bytearray(slot.read_bytes())
            for field, value in (
                (7, 31),
                (player + 3, 41),
                (actor + 2, 0),
                (actor + 3, 5),
                (actor + 15, 419),
            ):
                struct.pack_into("<i", seed, 12 + 4 * field, value)
            struct.pack_into("<I", seed, len(seed) - 4, checksum(seed[:-4]))
            slot.write_bytes(seed)
            play("1 0 0 0 0\n1 0 0 0 4\n", "--resume")
            assert payload()[actor + 2] == expected_hp
        print("An eligible fallen imp respawns on Nightmare and stays down on medium.")
        play("1 0 0 0 4\n", "--map", "E1M2")
        nuclear_start = slot.read_bytes()
        red_door = 99
        for keyed in (False, True):
            seed = nuclear_start
            if keyed:
                pose(seed, 1136, 352, 0)
                play("1 0 0 0 0\n1 0 0 0 4\n", "--resume")
                seed = slot.read_bytes()
            pose(seed, -690, 384, 2048)
            play("1 0 0 0 2\n15 0 0 0 0\n1 0 0 0 4\n", "--resume")
            delta = payload()[11 + red_door]
            assert delta > 0 if keyed else delta == 0
        print(
            "Nuclear Plant’s red door refuses use until the original red key is collected."
        )

        # Old map layouts have no blur-sphere slots. Insert the missing actors
        # without shifting the old monster IDs or losing the moving-sector state.
        play("37 0 0 0 0\n1 0 0 0 4\n", "--map", "E1M6")
        layout = index_layout(6)
        placed = sprites_in(layout)
        spheres = [i for i, thing in enumerate(placed) if thing[5] == 2024]
        assert len(spheres) == 2 and spheres == list(
            range(len(placed) - 2, len(placed))
        )
        player = 11 + layout[20] // 26
        actor_base = player + 48
        new_save = slot.read_bytes()
        for version in (2, 3):
            data = bytearray(new_save[:-4])
            struct.pack_into("<I", data, 4, version + 256 * 6)
            del data[
                12
                + 4 * (actor_base + 16 * spheres[0]) : 12
                + 4 * (actor_base + 16 * len(placed))
            ]
            if version == 2:
                del data[12 + 4 * (player + 16) : 12 + 4 * (player + 48)]
            data.extend(struct.pack("<I", checksum(data)))
            slot.write_bytes(data)
            play("1 0 0 0 4\n", "--resume")
            expected = bytearray(new_save)
            if version == 2:
                # The old 16-word player record predates vertical velocity and the extra player fields.
                expected[12 + 4 * (player + 16) : 12 + 4 * (player + 48)] = bytes(
                    32 * 4
                )
                struct.pack_into(
                    "<I", expected, len(expected) - 4, checksum(expected[:-4])
                )
            assert slot.read_bytes() == expected, ("legacy actor migration", version)
        for i in spheres:
            x, y = placed[i][:2]
            pose(slot.read_bytes(), x, y, 0)
            play("1 0 0 0 0\n1 0 0 0 4\n", "--resume")
            s = payload()
            assert s[player + 14] == 2100 and s[actor_base + 16 * i + 3] == 6
            play("5 0 0 0 0\n1 0 0 0 4\n", "--resume")
            assert payload()[player + 14] == 2095
        print(
            "Both Central Processing blur spheres grant partial invisibility; the timer and collected pickups survive save/load."
        )
        pose(baseline, 2190, -2432, 0)
        opening = "42 0 0 0 0\n"
        fight = "115 0 0 0 1\n22 1 0 0 0\n"
        complete = play(opening + "1 0 0 0 4\n" + fight, "--resume")
        assert (
            int(complete["kills"]) >= 1
            and int(complete["health"]) < 100
            and int(complete["DSITEMUP"]) >= 1
        ), complete
        resumed = play("1 0 0 0 0\n" + fight, "--resume")
        assert resumed["state"] == complete["state"], (resumed, complete)
        if renderers:
            for renderer in ("cpu", "gpu"):
                pose(baseline, 2190, -2432, 0)
                trace.write_text(opening + "1 0 0 0 4\n" + fight)
                result = subprocess.run(
                    [
                        str(executable),
                        "--iwad",
                        str(iwad),
                        "--index",
                        str(index),
                        "--renderer=" + renderer,
                        "--windowed",
                        "--hidden",
                        "--mute",
                        "--resume",
                        "--save",
                        str(slot),
                        "--replay",
                        str(trace),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=25,
                    check=True,
                )
                assert "state=" + complete["state"] in result.stdout, (
                    renderer,
                    result.stdout,
                )
                print(renderer, result.stdout.strip())
                trace.write_text("1 0 0 0 0\n" + fight)
                other = "gpu" if renderer == "cpu" else "cpu"
                cross = subprocess.run(
                    [
                        str(executable),
                        "--iwad",
                        str(iwad),
                        "--index",
                        str(index),
                        "--renderer=" + other,
                        "--sample-render",
                        "--windowed",
                        "--hidden",
                        "--resume",
                        "--save",
                        str(slot),
                        "--replay",
                        str(trace),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=25,
                    check=True,
                )
                assert "state=" + complete["state"] in cross.stdout, (
                    renderer,
                    other,
                    cross.stdout,
                )
                print(f"Combat save restored from {renderer} to {other}.")
        print(
            "Hangar encounter: alerted, injured, killed, collected clip and reproduced from a mid-fight save."
        )
        pose(baseline, 3376, -3472, 0)
        imp = play("105 0 0 0 0\n", "--resume")
        assert int(imp["health"]) < 100 and int(imp["awake"]) > 0, imp

        for number, exit_kind, destination in [(1, 1, 2), (3, 2, 9), (9, 1, 4)]:
            play("1 0 0 0 4\n", "--map", f"E1M{number}")
            seed = bytearray(slot.read_bytes())
            # This checkpoint isolates the intermission decision; route traversal is a separate test.
            struct.pack_into("<ii", seed, 12 + 5 * 4, 17, exit_kind)
            struct.pack_into("<I", seed, len(seed) - 4, checksum(seed[:-4]))
            slot.write_bytes(seed)
            next_level = play("1 0 0 0 2\n1 0 0 0 4\n", "--resume")
            assert (
                next_level["map"] == f"E1M{destination}" and next_level["ammo"] == "17"
            ), next_level
            restored = play("1 0 0 0 0\n", "--resume")
            assert restored["state"] == next_level["state"], (restored, next_level)
        print(
            "Verified level handoff, secret detour, inventory carry and cross-map restore."
        )
        # Short diagnostic checkpoint for the original two-Baron trigger.
        play("1 0 0 0 4\n", "--map", "E1M8")
        data = index.with_name(index.stem + ".e1m8.syi").read_bytes()
        layout = struct.unpack("<" + "i" * (len(data) // 4), data)
        sprites = 46 + 5 * layout[9] + 4 * layout[10] + 17 * layout[11]
        player = 11 + layout[20] // 26
        barons = [
            i
            for i in range(layout[12])
            if layout[sprites + 9 * i + 5] == 3003 and layout[sprites + 9 * i + 7] & 2
        ]
        assert len(barons) == 2
        sectors = wad[layout[19] : layout[19] + layout[20]]
        barrier = next(
            i
            for i, sector in enumerate(struct.iter_unpack("<hh8s8shhh", sectors))
            if sector[-1] == 666
        )
        for count, i in enumerate(barons, 1):
            seed = bytearray(slot.read_bytes())
            x, y = layout[sprites + 9 * i : sprites + 9 * i + 2]
            struct.pack_into("<3i", seed, 12, x * 256, (y - 22) * 256, 1024)
            struct.pack_into("<i", seed, 12 + 4 * (player + 48 + 16 * i + 2), 1)
            struct.pack_into("<I", seed, len(seed) - 4, checksum(seed[:-4]))
            slot.write_bytes(seed)
            result = play(
                ("16 0 0 0 0\n" if count == 2 else "")
                + "1 0 0 0 1\n5 0 0 0 0\n1 0 0 0 4\n",
                "--resume",
            )
            assert int(result["kills"]) == count, result
            offset = 12 + 4 * (player + 48 + 16 * layout[12] + 11 * barrier)
            delta = struct.unpack_from("<i", slot.read_bytes(), offset)[0]
            assert delta == 0 if count == 1 else delta < 0
        # The victory threshold is checked between damage pulses too.
        thing_lump = wad[layout[27] : layout[27] + layout[28]]
        destination = next(
            (x, y)
            for x, y, _, kind, _ in struct.iter_unpack("<5h", thing_lump)
            if kind == 14
        )
        seed = bytearray(slot.read_bytes())
        struct.pack_into("<2i", seed, 12, destination[0] * 256, destination[1] * 256)
        struct.pack_into("<i", seed, 12 + 4 * player, 10)
        struct.pack_into("<i", seed, 12 + 4 * (player + 38), 0)
        struct.pack_into("<I", seed, len(seed) - 4, checksum(seed[:-4]))
        slot.write_bytes(seed)
        assert play("1 0 0 0 0\n", "--resume")["exit"] == "1"
        print(
            "Phobos Anomaly arena stays closed after one Baron and opens after the second."
        )


def verify_episode(executable, iwad, index, renderers):
    evidence = Path(__file__).parent / "evidence"
    for route, order in [
        ("normal", [1, 2, 3, 4, 5, 6, 7, 8]),
        ("secret", [1, 2, 3, 9, 4, 5, 6, 7, 8]),
    ]:
        expected = [(n, 2 if n == 3 and route == "secret" else 1) for n in order]
        reference = None
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "commands.trace"
            trace.write_bytes(
                gzip.decompress((evidence / f"episode1-{route}.trace.gz").read_bytes())
            )
            for backend in ["headless", "cpu", "gpu"] if renderers else ["headless"]:
                options = (
                    ["--check"]
                    if backend == "headless"
                    else [
                        "--sample-render",
                        "--windowed",
                        "--hidden",
                        "--renderer=" + backend,
                    ]
                )
                result = subprocess.run(
                    [
                        executable,
                        "--iwad",
                        iwad,
                        "--index",
                        index,
                        "--replay",
                        trace,
                        *options,
                    ],
                    cwd=directory,
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=180,
                )
                milestones = re.findall(
                    r"^completed E1M(\d) exit=(\d) state=([0-9a-f]+)$",
                    result.stdout,
                    re.M,
                )
                assert [
                    (int(m), int(e)) for m, e, _ in milestones
                ] == expected, result.stdout
                assert "player died in" not in result.stdout, result.stdout
                entries = re.findall(
                    r"^verified E1M(\d) exit=0 state=([0-9a-f]+)$", result.stdout, re.M
                )
                assert [int(map_id) for map_id, _ in entries] == order, result.stdout
                hashes = [digest for _, digest in entries] + [
                    item[2] for item in milestones
                ]
                if reference is None:
                    reference = hashes
                assert hashes == reference, (backend, hashes, reference)
                print(route, backend, result.stdout.strip())


def benchmark(executable, iwad, index):
    """Run real-time slices using the normal clock, renderer and audio mixer."""
    archive = Path(__file__).parent / "evidence/episode1-secret.trace.gz"
    rows = [
        tuple(map(int, line.split()))
        for line in gzip.decompress(archive.read_bytes()).splitlines()
        if not line.startswith(b"expect ")
    ]

    def segment(start, stop):
        pos = 0
        result = []
        for duration, *cmd in rows:
            count = min(stop, pos + duration) - max(start, pos)
            if count > 0:
                result.append(" ".join(map(str, [count, *cmd])))
            pos += duration
            if pos >= stop:
                break
        return "\n".join(result) + "\n"

    cases = [
        ("Military Base firefight", 45500),
        ("Phobos Lab platforms", 53720),
        ("Central Processing exit into Computer Station", 85500),
    ]
    base = [executable, "--iwad", iwad, "--index", index]
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        trace = root / "commands.txt"
        slot = root / "sample.sav"
        for name, start in cases:
            trace.write_text(segment(0, start) + "checkpoint\n")
            subprocess.run(
                [*base, "--check", "--save", slot, "--replay", trace],
                check=True,
                capture_output=True,
                timeout=90,
            )
            trace.write_text(segment(start, start + 245))
            reference = None
            for backend in ("cpu", "gpu"):
                result = subprocess.run(
                    [
                        *base,
                        "--renderer=" + backend,
                        "--windowed",
                        "--hidden",
                        "--resume",
                        "--save",
                        slot,
                        "--replay",
                        trace,
                    ],
                    check=True,
                    text=True,
                    capture_output=True,
                    timeout=30,
                )
                metrics = dict(re.findall(r"(\w+)=([^\s]+)", result.stdout))
                assert (
                    metrics["ticks"] == "245" and int(metrics["audio_blocks"]) > 0
                ), result.stdout
                assert reference in (None, metrics["state"]), result.stdout
                reference = metrics["state"]
                print("Performance", name, backend, result.stdout.strip())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("iwad", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument(
        "--renderers",
        action="store_true",
        help="Also run the combat replay through both SDL renderers",
    )
    parser.add_argument(
        "--episode",
        action="store_true",
        help="Verify the continuous episode route and every exit",
    )
    parser.add_argument(
        "--performance",
        action="store_true",
        help="Profile three real-time gameplay slices on CPU and GPU",
    )
    options = parser.parse_args()
    run_checks(
        options.executable.resolve(),
        options.iwad.resolve(),
        (options.index or options.iwad.with_suffix(".syi")).resolve(),
        options.renderers,
    )
    if options.episode:
        verify_episode(
            options.executable.resolve(),
            options.iwad.resolve(),
            (options.index or options.iwad.with_suffix(".syi")).resolve(),
            options.renderers,
        )
    if options.performance:
        benchmark(
            options.executable.resolve(),
            options.iwad.resolve(),
            (options.index or options.iwad.with_suffix(".syi")).resolve(),
        )
