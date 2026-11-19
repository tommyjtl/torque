"""Episode 1 simulation, world rendering, menus and sound effects for DOOM shareware 1.9."""
import soundtrack
from std.ffi import external_call
from std.math import abs, atan2, cos, floor, max, min, sin, sqrt
from std.memory import MutPointer
from std.origin import MutUntrackedOrigin

comptime B = MutPointer[UInt8, MutUntrackedOrigin]
comptime I = MutPointer[Int32, MutUntrackedOrigin]
comptime F = MutPointer[Float32, MutUntrackedOrigin]
comptime P = MutPointer[UInt32, MutUntrackedOrigin]
comptime V = SIMD[DType.float32, 8]


def rd(b: B, n: Int) -> Int:
    return Int(b[unsafe_offset=n])


def w(b: B, n: Int) -> Int:
    return rd(b, n) + (rd(b, n + 1) << 8)


def signed(b: B, n: Int) -> Int:
    return Int(Int16(UInt16(w(b, n))))


def dw(b: B, n: Int) -> Int:
    return w(b, n) + (w(b, n + 2) << 16)


def word(i: I, n: Int) -> Int:
    return Int(i[unsafe_offset=n])


def point(x: Float32, y: Float32, z: Float32, u: Float32, v: Float32) -> V:
    return V(x, y, z, u, v, 0, 0, 0)


# State after the sector table: player fields, then one 16-word record per map thing.
comptime HEALTH = 0
comptime ARMOR = 1
comptime KILLS = 2
comptime RNG = 3
comptime SKILL = 4
comptime REFIRE = 5
comptime KEYS = 6
comptime SECRETS = 7
comptime SUIT = 8
comptime SHELLS = 9
comptime ROCKETS = 10
comptime WEAPONS = 11
comptime EQUIPPED = 12
comptime BACKPACK = 13
comptime INVIS = 14
comptime MAP_POWER = 15
comptime ITEMS = 16
comptime LIGHT_POWER = 17
comptime ARMOR_CLASS = 18
comptime PLAYER_MISSILE = 20
comptime FOOT_Z = 36
comptime FALL_SPEED = 37
comptime HEIGHT_READY = 38
comptime PLAYER_WORDS = 48
comptime FIST = 0
comptime PISTOL = 1
comptime SHOTGUN = 2
comptime CHAINGUN = 3
comptime LAUNCHER = 4
comptime SAW = 5
comptime FLOOR_DELTA = 0
comptime FLOOR_SPEED = 1
comptime FLOOR_GOAL = 2
comptime FLOOR_WAIT = 3
comptime FLOOR_RETURN = 4
comptime CEIL_SPEED = 5
comptime CEIL_GOAL = 6
comptime CEIL_WAIT = 7
comptime CEIL_RETURN = 8
comptime FOUND_SECRET = 9
comptime LIGHT = 10
comptime AX = 0
comptime AY = 1
comptime HP = 2
comptime MODE = 3
comptime TIMER = 4
comptime FACING = 5
comptime DROP = 6
comptime MX = 7
comptime MY = 8
comptime MZ = 9
comptime VX = 10
comptime VY = 11
comptime VZ = 12
comptime FLIGHT = 13
comptime TARGET = 14
comptime CORPSE_AGE = 15
comptime ASLEEP = 0
comptime CHASE = 1
comptime AIM = 2
comptime RECOVER = 3
comptime PAIN = 4
comptime DEAD = 5
comptime REMOVED = 6


def heading(dx: Float32, dy: Float32) -> Int:
    return Int(atan2(dy, dx) * 651.8986 + 4096.5) & 4095


def hit_points(kind: Int) -> Int:
    if kind in (3004, 2035):
        return 20
    if kind == 9:
        return 30
    if kind == 3001:
        return 60
    if kind == 3002 or kind == 58:
        return 150
    if kind == 3003:
        return 1000
    return 0


@fieldwise_init
struct Hangar(Copyable, Movable):
    var wad: B
    var ix: I
    var f: F
    var tex: P
    var bases: I
    var layout: I

    def sectors(self) -> Int:
        return word(self.ix, 20) // 26

    def player(self) -> Int:
        return 11 + self.sectors()

    def actor(self, i: Int) -> Int:
        return self.player() + PLAYER_WORDS + 16 * i

    def mover(self, sector: Int) -> Int:
        return self.actor(word(self.ix, 12)) + 11 * sector

    def line_state(self, line: Int) -> Int:
        return self.mover(self.sectors()) + line

    def state_size(self) -> Int:
        return self.line_state(self.length(1) // 14)

    def sprite(self, i: Int) -> Int:
        return 46 + 5 * word(self.ix, 9) + 4 * word(self.ix, 10) + 17 * word(self.ix, 11) + 9 * i

    def stops(self) -> Int:
        return self.sprite(word(self.ix, 12))

    def hud_table(self) -> Int:
        return self.stops() + self.sectors()

    def weapon_art(self) -> Int:
        return word(self.layout, 2)

    def ammo_slot(self, weapon: Int) -> Int:
        return (
            self.player() + SHELLS if weapon
            == SHOTGUN else self.player() + ROCKETS if weapon
            == LAUNCHER else 5
        )

    def choose_weapon(self, s: I, selection: Int):
        var p = self.player()
        var current = word(s, p + EQUIPPED)
        if selection >= 0:
            if selection <= SAW and (word(s, p + WEAPONS) & (1 << selection)):
                s[unsafe_offset=p + EQUIPPED] = Int32(selection)
            return
        for offset in range(1, 7):
            var candidate = (current + offset) % 6
            if (word(s, p + WEAPONS) & (1 << candidate)) and (
                candidate in (FIST, SAW) or word(s, self.ammo_slot(candidate)) > 0
            ):
                s[unsafe_offset=p + EQUIPPED] = Int32(candidate)
                return

    def texture_styles(self) -> Int:
        return word(self.layout, 6)

    def animated(self, s: I, mat: Int, line: Int) -> Int:
        var rec = self.texture_styles() + 6 * mat
        var other = word(self.ix, rec)
        if other >= 0 and line >= 0:
            var flags = word(s, self.line_state(line))
            if flags & 4 and ((flags >> 3) == 0 or word(s, 7) < (flags >> 3)):
                return other
        var count = word(self.ix, rec + 1)
        return word(self.ix, rec + 2 + (word(s, 7) // 8) % count) if count else mat

    def rand(self, s: I, n: Int) -> Int:
        var k = self.player() + RNG
        var value = (word(s, k) * 1664525 + 1013904223) & 0x7FFFFFFF
        s[unsafe_offset=k] = Int32(value)
        return (value >> 12) % n

    def lump(self, k: Int) -> Int:
        if k >= 14:
            return word(self.ix, word(self.layout, 1) + 2 * (k - 14))
        return word(self.ix, 13 + 2 * k)

    def length(self, k: Int) -> Int:
        if k >= 14:
            return word(self.ix, word(self.layout, 1) + 2 * (k - 14) + 1)
        return word(self.ix, 14 + 2 * k)

    def desc(self, mat: Int, k: Int) -> Int:
        return word(self.ix, 46 + mat * 5 + k)

    def source(self, mat: Int, light: Int) -> Int:
        return word(self.bases, mat) + light * self.desc(mat, 0) * self.desc(mat, 1)

    def rgba(self, index: Int, light: Int) -> UInt32:
        var c = self.lump(8) + 3 * rd(self.wad, self.lump(9) + 1024 * light + index)
        return UInt32(0xFF000000) | UInt32(
            rd(self.wad, c) << 16 | rd(self.wad, c + 1) << 8 | rd(self.wad, c + 2)
        )

    def decode(self, refill: Bool = False):
        var stride = 0
        var layer0 = 46 + 5 * word(self.ix, 9)
        for mat in range(word(self.ix, 9)):
            self.bases[unsafe_offset=mat] = Int32(stride)
            var width = self.desc(mat, 0)
            var height = self.desc(mat, 1)
            var area = width * height
            for layer in range(self.desc(mat, 3)):
                var l = layer0 + 4 * (self.desc(mat, 2) + layer)
                var ox = word(self.ix, l)
                var oy = word(self.ix, l + 1)
                var data = word(self.ix, l + 2)
                if self.desc(mat, 4) == 1:
                    for k in range(area):
                        self.tex[unsafe_offset=stride + k] = UInt32(rd(self.wad, data + k) + 1)
                else:
                    var pw = w(self.wad, data)
                    for px in range(pw):
                        if ox + px < 0 or ox + px >= width:
                            continue
                        var post = data + dw(self.wad, data + 8 + 4 * px)
                        while rd(self.wad, post) != 255:
                            var py = rd(self.wad, post) + oy
                            var count = rd(self.wad, post + 1)
                            for j in range(count):
                                if py + j >= 0 and py + j < height:
                                    self.tex[
                                        unsafe_offset=stride + (py + j) * width + ox + px
                                    ] = UInt32(rd(self.wad, post + 3 + j) + 1)
                            post += count + 4
            for k in range(area):
                var idx = Int(self.tex[unsafe_offset=stride + k]) - 1
                if idx >= 0:
                    for light in range(4):
                        self.tex[unsafe_offset=stride + light * area + k] = self.rgba(idx, light)
            stride += 4 * area
            if refill and mat % 8 == 0:
                pump_audio(self, external_call["cl_voices", I]())

    def upload(self, refill: Bool = False):
        for mat in range(word(self.ix, 9)):
            if refill and mat % 8 == 0:
                pump_audio(self, external_call["cl_voices", I]())
            for shade in range(4):
                _ = external_call["cl_upload", Int32](
                    Int32(4 * mat + shade),
                    Int32(self.desc(mat, 0)),
                    Int32(self.desc(mat, 1)),
                    self.tex.unsafe_offset(self.source(mat, shade)),
                )

    def sector(self, x: Float32, y: Float32) -> Int:
        var node = self.length(6) // 28 - 1
        while node < 32768:
            var p = self.lump(6) + 28 * node
            var side = Int(
                Float32(signed(self.wad, p + 4)) * (y - Float32(signed(self.wad, p + 2)))
                > Float32(signed(self.wad, p + 6)) * (x - Float32(signed(self.wad, p)))
            )
            node = w(self.wad, p + 24 + 2 * side)
        var first = w(self.wad, self.lump(5) + (node - 32768) * 4 + 2)
        var seg = self.lump(4) + first * 12
        var line = self.lump(1) + 14 * w(self.wad, seg + 6)
        return self.side_sector(w(self.wad, line + 10 + 2 * w(self.wad, seg + 8)))

    def side_sector(self, side: Int) -> Int:
        return w(self.wad, self.lump(2) + 30 * side + 28)

    def height(self, s: I, k: Int) -> Int:
        var sector = k // 2
        var h = signed(self.wad, self.lump(3) + 26 * sector + 2 * (k & 1))
        return h + (word(s, 11 + sector) if k & 1 else word(s, self.mover(sector) + FLOOR_DELTA))

    def feet(self, s: I) -> Float32:
        var p = self.player()
        if word(s, p + HEIGHT_READY):
            return Float32(word(s, p + FOOT_Z)) / 256
        return Float32(
            self.height(s, 2 * self.sector(Float32(word(s, 0)) / 256, Float32(word(s, 1)) / 256))
        )

    def gravity(self, s: I, sector: Int):
        var p = self.player()
        var ground = 256 * self.height(s, 2 * sector)
        if not word(s, p + HEIGHT_READY) or word(s, p + FOOT_Z) <= ground:
            s[unsafe_offset=p + FOOT_Z] = Int32(ground)
            s[unsafe_offset=p + FALL_SPEED] = 0
        else:
            var speed = word(s, p + FALL_SPEED)
            speed = -512 if speed == 0 else max(-8192, speed - 256)
            var z = max(ground, word(s, p + FOOT_Z) + speed)
            s[unsafe_offset=p + FOOT_Z] = Int32(z)
            s[unsafe_offset=p + FALL_SPEED] = Int32(0 if z == ground else speed)
        s[unsafe_offset=p + HEIGHT_READY] = 1

    def endpoints(self, i: Int) -> Tuple[Float32, Float32, Float32, Float32]:
        var l = self.lump(1) + 14 * i
        var a = self.lump(0) + 4 * w(self.wad, l)
        var b = self.lump(0) + 4 * w(self.wad, l + 2)
        return (
            Float32(signed(self.wad, a)),
            Float32(signed(self.wad, a + 2)),
            Float32(signed(self.wad, b)),
            Float32(signed(self.wad, b + 2)),
        )

    def spawn(self, s: I, chosen_skill: Int = 0):
        for k in range(self.state_size()):
            s[unsafe_offset=k] = 0
        s[unsafe_offset=5] = 50
        for sec in range(self.sectors()):
            s[unsafe_offset=self.mover(sec) + LIGHT] = -1
        var player = self.player()
        var skill = chosen_skill if chosen_skill else Int(external_call["cl_skill", Int32]())
        s[unsafe_offset=player + HEALTH] = 100
        s[unsafe_offset=player + SKILL] = Int32(skill)
        s[unsafe_offset=player + RNG] = 1
        s[unsafe_offset=player + WEAPONS] = 3
        s[unsafe_offset=player + EQUIPPED] = PISTOL
        self.spawn_actors(s, 0)
        for i in range(self.length(7) // 10):
            var t = self.lump(7) + i * 10
            if w(self.wad, t + 6) == 1:
                s[unsafe_offset=0] = Int32(signed(self.wad, t) * 256)
                s[unsafe_offset=1] = Int32(signed(self.wad, t + 2) * 256)
                s[unsafe_offset=2] = Int32((w(self.wad, t + 4) * 4096 // 360) & 4095)
                return

    def spawn_actors(self, s: I, first: Int):
        var skill = word(s, self.player() + SKILL)
        var filter = 1 if skill <= 2 else 2 if skill == 3 else 4
        for i in range(first, word(self.ix, 12)):
            var t = self.sprite(i)
            var a = self.actor(i)
            s[unsafe_offset=a + AX] = Int32(word(self.ix, t) * 256)
            s[unsafe_offset=a + AY] = Int32(word(self.ix, t + 1) * 256)
            s[unsafe_offset=a + FACING] = Int32((word(self.ix, t + 6) * 4096 // 360) & 4095)
            s[unsafe_offset=a + HP] = Int32(hit_points(word(self.ix, t + 5)))
            if not (word(self.ix, t + 7) & filter):
                s[unsafe_offset=a + MODE] = REMOVED

    def can_move(
        self, s: I, x: Float32, y: Float32, oldfloor: Int, old_x: Float32, old_y: Float32
    ) -> Bool:
        if self.height(s, 2 * self.sector(x, y)) - oldfloor > 24:
            return False
        for i in range(self.length(1) // 14):
            var l = self.lump(1) + 14 * i
            var ax, ay, bx, by = self.endpoints(i)
            if (
                x < min(ax, bx) - 11
                or y < min(ay, by) - 11
                or x > max(ax, bx) + 11
                or y > max(ay, by) + 11
            ):
                continue
            var back = w(self.wad, l + 12)
            if back != 65535 and not (w(self.wad, l + 4) & 1):
                var sa = self.side_sector(w(self.wad, l + 10)) * 2
                var sb = self.side_sector(back) * 2
                var higher = max(self.height(s, sa), self.height(s, sb))
                if (
                    min(self.height(s, sa + 1), self.height(s, sb + 1)) - higher >= 56
                    and higher - oldfloor <= 24
                ):
                    continue
            var dx = bx - ax
            var dy = by - ay
            var t = max(
                Float32(0),
                min(
                    Float32(1),
                    ((x - ax) * dx + (y - ay) * dy) / max(Float32(0.01), dx * dx + dy * dy),
                ),
            )
            var distance = (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2
            if distance < 100:
                # After stepping off a ledge the old footprint may still overlap
                # its lip. Allow separation on the landing side.
                var prev = max(
                    Float32(0),
                    min(
                        Float32(1),
                        ((old_x - ax) * dx + (old_y - ay) * dy)
                        / max(Float32(0.01), dx * dx + dy * dy),
                    ),
                )
                var previous = (old_x - ax - prev * dx) ** 2 + (old_y - ay - prev * dy) ** 2
                var same_side = ((old_x - ax) * dy - (old_y - ay) * dx) * (
                    (x - ax) * dy - (y - ay) * dx
                ) >= 0
                if same_side and distance >= previous and previous < 100:
                    continue
                return False
        return True

    def adjacent(self, sector: Int, line: Int) -> Int:
        var l = self.lump(1) + line * 14
        var back = w(self.wad, l + 12)
        if back == 65535:
            return -1
        var a = self.side_sector(w(self.wad, l + 10))
        var b = self.side_sector(back)
        if a == b:
            return -1
        return b if a == sector else a if b == sector else -1

    def floor_move(self, s: I, sec: Int, goal: Int, speed: Int, wait: Int = 0):
        var m = self.mover(sec)
        var current = self.height(s, sec * 2)
        if word(s, m + FLOOR_SPEED) or word(s, m + FLOOR_WAIT) or current == goal:
            return
        s[unsafe_offset=m + FLOOR_SPEED] = Int32(speed)
        s[unsafe_offset=m + FLOOR_GOAL] = Int32(goal)
        s[unsafe_offset=m + FLOOR_RETURN] = Int32(current)
        s[unsafe_offset=m + FLOOR_WAIT] = Int32(-wait)

    def start_mover(self, s: I, sec: Int, special: Int, front: Int = -1):
        var m = self.mover(sec)
        var floor_z = self.height(s, sec * 2)
        var ceiling = self.height(s, sec * 2 + 1)
        var min_floor = floor_z
        var high_neighbor = -32768
        var next_floor = 32768
        var min_ceiling = 32768
        var first = -1
        for i in range(self.length(1) // 14):
            var near = self.adjacent(sec, i)
            if near < 0:
                continue
            if first < 0:
                first = near
            var f = self.height(s, near * 2)
            min_floor = min(min_floor, f)
            high_neighbor = max(high_neighbor, f)
            if f > floor_z:
                next_floor = min(next_floor, f)
            min_ceiling = min(min_ceiling, self.height(s, near * 2 + 1))
        if first < 0:
            return
        if special in (1, 2, 16, 26, 27, 28, 31, 32, 33, 34, 46, 63, 76, 86, 90, 103):
            var closing = special in (16, 76)
            var goal = floor_z if closing else min_ceiling - 4
            if word(s, m + CEIL_SPEED) and not (special in (1, 26, 27, 28)):
                return
            s[unsafe_offset=m + CEIL_SPEED] = 2
            s[unsafe_offset=m + CEIL_GOAL] = Int32(goal)
            s[unsafe_offset=m + CEIL_RETURN] = Int32(ceiling if closing else floor_z)
            s[unsafe_offset=m + CEIL_WAIT] = Int32(
                -1050 if closing else -150 if special in (1, 26, 27, 28, 63, 90) else 0
            )
        elif special in (62, 88):
            self.floor_move(s, sec, min_floor, 4, 105)
        elif special in (18, 20, 22):
            if special != 18 and front >= 0 and not word(s, m + FLOOR_SPEED):
                var source = word(s, self.mover(front) + FOUND_SECRET) >> 1
                s[unsafe_offset=m + FOUND_SECRET] = Int32(
                    (word(s, m + FOUND_SECRET) & 1) | ((source if source else front + 1) << 1)
                )
            if next_floor < 32768:
                self.floor_move(s, sec, next_floor, 1)
        elif special in (23, 82):
            self.floor_move(s, sec, min_floor, 1)
        elif special in (36, 70, 98):
            self.floor_move(s, sec, high_neighbor + 8 if high_neighbor != floor_z else floor_z, 4)
        elif special in (5, 91):
            self.floor_move(s, sec, min(ceiling, min_ceiling), 1)
        elif special == 35:
            s[unsafe_offset=m + LIGHT] = 35
        elif special in (7, 8):
            var stair = sec
            var target = floor_z + 8
            var flat = self.lump(3) + 26 * sec + 4
            for _ in range(self.sectors()):
                self.floor_move(s, stair, target, 1)
                var next_sec = -1
                for i in range(self.length(1) // 14):
                    var line = self.lump(1) + 14 * i
                    if self.side_sector(w(self.wad, line + 10)) != stair:
                        continue
                    var other = self.adjacent(stair, i)
                    if other < 0 or word(s, self.mover(other) + FLOOR_SPEED):
                        continue
                    var tex = self.lump(3) + 26 * other + 4
                    if dw(self.wad, tex) == dw(self.wad, flat) and dw(self.wad, tex + 4) == dw(
                        self.wad, flat + 4
                    ):
                        next_sec = other
                        break
                if next_sec < 0:
                    break
                stair = next_sec
                target += 8
        elif special == 9:
            for i in range(self.length(1) // 14):
                var outside = self.adjacent(first, i)
                if outside >= 0 and outside != sec:
                    var target = self.height(s, outside * 2)
                    self.floor_move(s, sec, target, 1)
                    self.floor_move(s, first, target, 1)
                    break

    def advance_movers(self, s: I, player_sector: Int):
        for sec in range(self.sectors()):
            var m = self.mover(sec)
            for plane in range(2):
                var speed_slot = m + (CEIL_SPEED if plane else FLOOR_SPEED)
                var goal_slot = speed_slot + 1
                var wait_slot = speed_slot + 2
                var delta_slot = 11 + sec if plane else m + FLOOR_DELTA
                var delay = word(s, wait_slot)
                if delay > 0:
                    s[unsafe_offset=wait_slot] -= 1
                    if delay == 1:
                        s[unsafe_offset=goal_slot] = s[unsafe_offset=speed_slot + 3]
                        s[unsafe_offset=speed_slot] = 2 if plane else 4
                    continue
                var speed = word(s, speed_slot)
                if speed == 0:
                    continue
                var height = self.height(s, 2 * sec + plane)
                var goal = word(s, goal_slot)
                var step = min(speed, max(-speed, goal - height))
                if plane and step < 0 and height + step < self.height(s, sec * 2) + 56:
                    var obstructed = sec == player_sector
                    if not obstructed:
                        for i in range(word(self.ix, 12)):
                            var a = self.actor(i)
                            if (
                                word(s, a + HP) > 0
                                and word(s, a + MODE) < DEAD
                                and self.sector(
                                    Float32(word(s, a + AX)) / 256, Float32(word(s, a + AY)) / 256
                                )
                                == sec
                            ):
                                obstructed = True
                                break
                    if obstructed:
                        s[unsafe_offset=goal_slot] = Int32(
                            signed(self.wad, self.lump(3) + sec * 26 + 2)
                            + word(self.ix, self.stops() + sec)
                        )
                        s[unsafe_offset=wait_slot] = -150
                        s[unsafe_offset=speed_slot + 3] = Int32(goal)
                        continue
                s[unsafe_offset=delta_slot] += Int32(step)
                if height + step == goal:
                    s[unsafe_offset=speed_slot] = 0
                    s[unsafe_offset=wait_slot] = Int32(-delay)

    def activate(self, s: I, index: Int, trigger: Int) -> Int:
        # Use, crossing and gun impact are distinct Doom activation modes.
        if word(s, self.line_state(index)) & 1:
            return -1
        var l = self.lump(1) + 14 * index
        var sp = w(self.wad, l + 6)
        if trigger == 0 and sp not in (
            1,
            7,
            9,
            11,
            18,
            20,
            23,
            26,
            27,
            28,
            31,
            32,
            33,
            34,
            51,
            62,
            63,
            70,
            103,
        ):
            return -1
        if trigger == 1 and sp not in (2, 5, 8, 16, 22, 35, 36, 76, 82, 86, 88, 90, 91, 97, 98):
            return -1
        if trigger == 2 and sp != 46:
            return -1
        if sp in (11, 51):
            s[unsafe_offset=6] = 2 if sp == 51 else 1
            return 12
        var key = 1 if sp in (26, 32) else 2 if sp in (27, 34) else 4 if sp in (28, 33) else 0
        if key and not (word(s, self.player() + KEYS) & key):
            return -1
        var tag = w(self.wad, l + 8)
        if sp in (1, 26, 27, 28, 31, 32, 33, 34):
            var back = w(self.wad, l + 12)
            if back == 65535:
                return -1
            self.start_mover(s, self.side_sector(back), sp)
        elif sp == 97:
            for i in range(self.length(7) // 10):
                var t = self.lump(7) + i * 10
                if w(self.wad, t + 6) != 14:
                    continue
                var x = signed(self.wad, t)
                var y = signed(self.wad, t + 2)
                if w(self.wad, self.lump(3) + 26 * self.sector(Float32(x), Float32(y)) + 24) == tag:
                    s[unsafe_offset=0] = Int32(x * 256)
                    s[unsafe_offset=1] = Int32(y * 256)
                    s[unsafe_offset=2] = Int32((w(self.wad, t + 4) * 4096 // 360) & 4095)
                    s[unsafe_offset=self.player() + HEIGHT_READY] = 0
                    break
        else:
            if tag == 0:
                return -1
            for sec in range(self.sectors()):
                if w(self.wad, self.lump(3) + 26 * sec + 24) == tag:
                    self.start_mover(s, sec, sp, self.side_sector(w(self.wad, l + 10)))
        if trigger == 0:
            var line_slot = self.line_state(index)
            var until = (word(s, 7) + 35) if sp in (62, 63, 70) else 0
            s[unsafe_offset=line_slot] = Int32((word(s, line_slot) & 3) | 4 | (until << 3))
        if sp not in (1, 26, 27, 28, 46, 62, 63, 70, 76, 82, 86, 88, 90, 91, 97, 98):
            s[unsafe_offset=self.line_state(index)] |= 1
        return 11 if sp in (1, 2, 26, 27, 28, 31, 32, 33, 34, 46, 63, 86, 90, 103) else 12

    def discover(self, s: I, x: Float32, y: Float32):
        var z = Float32(self.height(s, 2 * self.sector(x, y)) + 40)
        for i in range(word(s, 7) % 16, self.length(1) // 14, 16):
            if word(s, self.line_state(i)) & 2:
                continue
            var ax, ay, bx, by = self.endpoints(i)
            var dx = bx - ax
            var dy = by - ay
            var t = max(
                Float32(0.01),
                min(
                    Float32(0.99),
                    ((x - ax) * dx + (y - ay) * dy) / max(Float32(0.01), dx * dx + dy * dy),
                ),
            )
            var tx = ax + dx * t
            var ty = ay + dy * t
            if (tx - x) ** 2 + (ty - y) ** 2 <= 768 * 768 and self.clear_path(
                s, x, y, z, x + (tx - x) * 0.995, y + (ty - y) * 0.995, z
            ):
                s[unsafe_offset=self.line_state(i)] |= 2

    def shade(self, s: I, sec: Int) -> Int:
        if word(s, self.player() + LIGHT_POWER) > 0:
            return 0
        var spec = w(self.wad, self.lump(3) + 26 * sec + 22)
        var level = word(s, self.mover(sec) + LIGHT)
        if level < 0:
            level = rd(self.wad, self.lump(3) + 26 * sec + 20)
            var tick = word(s, 7)
            if spec == 8:
                level -= abs((tick % 64) - 32) * 2
            elif spec in (2, 3, 12, 13):
                var period = 20 if spec in (2, 13) else 40
                if (tick + (0 if spec in (12, 13) else sec * 7)) % period >= 5:
                    level -= 80
            elif spec == 1 and ((tick // 8 + sec) * 13) % 17 < 5:
                level -= 65
        return min(3, max(0, (255 - level) // 48))

    def cross_lines(self, s: I, x: Float32, y: Float32, nx: Float32, ny: Float32) -> Int:
        if nx == x and ny == y:
            return -1
        var effect = -1
        for i in range(self.length(1) // 14):
            var l = self.lump(1) + 14 * i
            if not w(self.wad, l + 6):
                continue
            var ax, ay, bx, by = self.endpoints(i)
            var lx = bx - ax
            var ly = by - ay
            var d = (nx - x) * ly - (ny - y) * lx
            if abs(d) < 0.00001:
                continue
            var t = ((ax - x) * ly - (ay - y) * lx) / d
            var u = ((ax - x) * (ny - y) - (ay - y) * (nx - x)) / d
            if t > 0 and t <= 1 and u >= 0 and u <= 1:
                if w(self.wad, l + 6) == 97 and (lx * (y - ay) - ly * (x - ax)) > 0:
                    continue
                var sound = self.activate(s, i, 1)
                if sound >= 0:
                    effect = sound
        return effect

    def clear_path(
        self, s: I, x: Float32, y: Float32, z: Float32, tx: Float32, ty: Float32, tz: Float32
    ) -> Bool:
        var dx = tx - x
        var dy = ty - y
        for i in range(self.length(1) // 14):
            var ax, ay, bx, by = self.endpoints(i)
            if (
                max(ax, bx) < min(x, tx)
                or min(ax, bx) > max(x, tx)
                or max(ay, by) < min(y, ty)
                or min(ay, by) > max(y, ty)
            ):
                continue
            var lx = bx - ax
            var ly = by - ay
            var det = dx * ly - dy * lx
            if abs(det) < 0.0001:
                continue
            var t = ((ax - x) * ly - (ay - y) * lx) / det
            var u = ((ax - x) * dy - (ay - y) * dx) / det
            if t <= 0 or t >= 1 or u < 0 or u > 1:
                continue
            var line = self.lump(1) + 14 * i
            var back = w(self.wad, line + 12)
            if back == 65535:
                return False
            var frontsec = 2 * self.side_sector(w(self.wad, line + 10))
            var backsec = 2 * self.side_sector(back)
            var ray_z = z + t * (tz - z)
            if ray_z <= Float32(
                max(self.height(s, frontsec), self.height(s, backsec))
            ) or ray_z >= Float32(min(self.height(s, frontsec + 1), self.height(s, backsec + 1))):
                return False
        return True

    def sound_reach(self, s: I, origin: Int, heard: I):
        # Each reachable sector remembers whether sound crossed one sound-blocking line.
        for sec in range(self.sectors()):
            heard[unsafe_offset=sec] = 2
        heard[unsafe_offset=origin] = 0
        var changed = True
        while changed:
            changed = False
            for i in range(self.length(1) // 14):
                var line = self.lump(1) + 14 * i
                var back = w(self.wad, line + 12)
                if back == 65535:
                    continue
                var a = self.side_sector(w(self.wad, line + 10))
                var b = self.side_sector(back)
                if word(heard, a) == word(heard, b):
                    continue
                if word(heard, a) > word(heard, b):
                    var tmp = a
                    a = b
                    b = tmp
                var cost = word(heard, a) + Int((w(self.wad, line + 4) & 64) != 0)
                if cost >= word(heard, b):
                    continue
                var bottom = max(self.height(s, 2 * a), self.height(s, 2 * b))
                var top = min(self.height(s, 2 * a + 1), self.height(s, 2 * b + 1))
                if top > bottom:
                    heard[unsafe_offset=b] = Int32(cost)
                    changed = True

    def occupied(self, s: I, x: Float32, y: Float32, ignore: Int) -> Bool:
        for i in range(word(self.ix, 12)):
            var a = self.actor(i)
            if i == ignore or word(s, a + MODE) >= DEAD or word(s, a + HP) <= 0:
                continue
            var dx = Float32(word(s, a + AX)) / 256 - x
            var dy = Float32(word(s, a + AY)) / 256 - y
            if abs(dx) < 32 and abs(dy) < 32 and dx * dx + dy * dy < 32 * 32:
                return True
        return False

    def sound_at(self, s: I, voices: I, sound: Int, x: Float32, y: Float32):
        var dx = x - Float32(word(s, 0)) / 256
        var dy = y - Float32(word(s, 1)) / 256
        var range = max(Float32(1), sqrt(dx * dx + dy * dy))
        var gain = max(Float32(0), min(Float32(1), (1200 - range) / 1040))
        if gain <= 0:
            return
        var facing = Float32(word(s, 2)) * 0.0015339808
        var pan = (dx * sin(facing) - dy * cos(facing)) / range * 0.75
        start_sound(self, voices, sound, gain * (1 - pan), gain * (1 + pan))

    def hurt_player(self, s: I, voices: I, damage: Int):
        var p = self.player()
        if word(s, p + HEALTH) <= 0:
            return
        var hit = max(1, damage // 2) if word(s, p + SKILL) == 1 else damage
        var saved = min(word(s, p + ARMOR), hit // (2 if word(s, p + ARMOR_CLASS) == 2 else 3))
        s[unsafe_offset=p + ARMOR] -= Int32(saved)
        s[unsafe_offset=p + HEALTH] = Int32(max(0, word(s, p + HEALTH) - hit + saved))
        start_sound(self, voices, 23 if word(s, p + HEALTH) == 0 else 22)

    def shoot(
        self,
        s: I,
        voices: I,
        x: Float32,
        y: Float32,
        ca: Float32,
        sn: Float32,
        reach: Int = 2048,
        melee: Bool = False,
    ):
        var distance = Float32(reach)
        var target = -1
        var eye = self.feet(s) + 36
        for i in range(word(self.ix, 12)):
            var a = self.actor(i)
            if word(s, a + HP) <= 0 or word(s, a + MODE) >= DEAD:
                continue
            var tx = Float32(word(s, a + AX)) / 256
            var ty = Float32(word(s, a + AY)) / 256
            var dx = tx - x
            var dy = ty - y
            var depth = dx * ca + dy * sn
            if depth <= 0 or depth >= distance or abs(dx * sn - dy * ca) > 20:
                continue
            var z = Float32(self.height(s, 2 * self.sector(tx, ty)) + 28)
            if abs(z - eye) <= depth * 0.65 + 24 and self.clear_path(s, x, y, eye, tx, ty, z):
                distance = depth
                target = i
        if target < 0:
            return
        self.hurt_actor(
            s, voices, target, 2 * (1 + self.rand(s, 10)) if melee else 5 * (1 + self.rand(s, 3))
        )

    def hurt_actor(self, s: I, voices: I, target: Int, damage: Int, source: Int = -1):
        var a = self.actor(target)
        var kind = word(self.ix, self.sprite(target) + 5)
        s[unsafe_offset=a + TARGET] = Int32(source + 1)
        s[unsafe_offset=a + HP] -= Int32(damage)
        if word(s, a + HP) <= 0:
            s[unsafe_offset=a + HP] = 0
            s[unsafe_offset=a + MODE] = DEAD
            s[unsafe_offset=a + TIMER] = 25
            s[unsafe_offset=a + DROP] = Int32(kind == 3004 or kind == 9)
            if kind == 2035:
                s[unsafe_offset=a + TIMER] = 15
                self.sound_at(
                    s, voices, 35, Float32(word(s, a + AX)) / 256, Float32(word(s, a + AY)) / 256
                )
                return
            s[unsafe_offset=self.player() + KILLS] += 1
            if kind == 3003 and external_call["cl_map", Int32]() == 8:
                var any_baron = False
                for j in range(word(self.ix, 12)):
                    var other = self.actor(j)
                    if (
                        word(self.ix, self.sprite(j) + 5) == 3003
                        and word(s, other + HP) > 0
                        and word(s, other + MODE) < DEAD
                    ):
                        any_baron = True
                        break
                if not any_baron:
                    for sec in range(self.sectors()):
                        if w(self.wad, self.lump(3) + 26 * sec + 24) == 666:
                            self.start_mover(s, sec, 23)
            self.sound_at(
                s,
                voices,
                18 if kind == 3001 else 27 if kind in (3002, 58) else 29 if kind == 3003 else 17,
                Float32(word(s, a + AX)) / 256,
                Float32(word(s, a + AY)) / 256,
            )
        else:
            s[unsafe_offset=a + MODE] = PAIN
            s[unsafe_offset=a + TIMER] = 5
            self.sound_at(
                s, voices, 16, Float32(word(s, a + AX)) / 256, Float32(word(s, a + AY)) / 256
            )

    def acquire(self, s: I, kind: Int, dropped: Bool) -> Bool:
        var p = self.player()
        var scale = 2 if word(s, p + SKILL) in (1, 5) else 1
        var capacity = 2 if word(s, p + BACKPACK) else 1
        if kind in (5, 6, 13):
            var bit = 1 if kind == 5 else 2 if kind == 6 else 4
            s[unsafe_offset=p + KEYS] |= Int32(bit)
        elif kind in (2007, 2048, 2008, 2049, 2010, 2046):
            var slot = (
                5 if kind in (2007, 2048) else p + SHELLS if kind in (2008, 2049) else p + ROCKETS
            )
            var cap = capacity * (200 if slot == 5 else 50)
            if word(s, slot) >= cap:
                return False
            var amount = (
                5 if dropped else 10 if kind
                == 2007 else 50 if kind
                == 2048 else 4 if kind
                == 2008 else 20 if kind
                == 2049 else 1 if kind
                == 2010 else 5
            )
            s[unsafe_offset=slot] = Int32(min(cap, word(s, slot) + amount * scale))
        elif kind in (2001, 2002, 2003, 2005):
            var weapon = (
                SHOTGUN if kind
                == 2001 else CHAINGUN if kind
                == 2002 else LAUNCHER if kind
                == 2003 else SAW
            )
            var already = (word(s, p + WEAPONS) & (1 << weapon)) != 0
            var slot = self.ammo_slot(weapon)
            var cap = capacity * (200 if slot == 5 else 50)
            if already and (weapon == SAW or word(s, slot) >= cap):
                return False
            if weapon != SAW:
                var amount = (
                    (4 if weapon == SHOTGUN else 10 if weapon == CHAINGUN else 1)
                    * (1 if dropped else 2)
                    * scale
                )
                s[unsafe_offset=slot] = Int32(min(cap, word(s, slot) + amount))
            if not already:
                s[unsafe_offset=p + WEAPONS] |= Int32(1 << weapon)
                s[unsafe_offset=p + EQUIPPED] = Int32(weapon)
        elif kind == 8:
            s[unsafe_offset=p + BACKPACK] = 1
            s[unsafe_offset=5] = Int32(min(400, word(s, 5) + 10 * scale))
            s[unsafe_offset=p + SHELLS] = Int32(min(100, word(s, p + SHELLS) + 4 * scale))
            s[unsafe_offset=p + ROCKETS] = Int32(min(100, word(s, p + ROCKETS) + scale))
        elif kind in (2018, 2019):
            var protection = 100 if kind == 2018 else 200
            if word(s, p + ARMOR) >= protection:
                return False
            s[unsafe_offset=p + ARMOR] = Int32(protection)
            s[unsafe_offset=p + ARMOR_CLASS] = 1 if kind == 2018 else 2
        elif kind == 2015:
            s[unsafe_offset=p + ARMOR] = Int32(min(200, word(s, p + ARMOR) + 1))
            if not word(s, p + ARMOR_CLASS):
                s[unsafe_offset=p + ARMOR_CLASS] = 1
        elif kind in (2011, 2012, 2013, 2014):
            var cap = 200 if kind in (2013, 2014) else 100
            if word(s, p + HEALTH) >= cap and kind in (2011, 2012):
                return False
            var gain = 100 if kind == 2013 else 1 if kind == 2014 else 10 if kind == 2011 else 25
            s[unsafe_offset=p + HEALTH] = Int32(min(cap, word(s, p + HEALTH) + gain))
        elif kind == 2025:
            s[unsafe_offset=p + SUIT] = 2100
        elif kind == 2024:
            s[unsafe_offset=p + INVIS] = 2100
        elif kind == 2026:
            s[unsafe_offset=p + MAP_POWER] = 1
        elif kind == 2045:
            s[unsafe_offset=p + LIGHT_POWER] = 4200
        else:
            return False
        if kind in (83, 2013, 2014, 2015, 2024, 2026, 2045):
            s[unsafe_offset=p + ITEMS] += 1
        return True

    def blast(self, s: I, voices: I, x: Float32, y: Float32, z: Float32):
        for i in range(word(self.ix, 12)):
            var a = self.actor(i)
            if word(s, a + MODE) >= DEAD or word(s, a + HP) <= 0:
                continue
            var tx = Float32(word(s, a + AX)) / 256
            var ty = Float32(word(s, a + AY)) / 256
            var damage = 128 - max(0, Int(max(abs(tx - x), abs(ty - y))) - 20)
            if damage > 0 and self.clear_path(
                s, x, y, z, tx, ty, Float32(self.height(s, 2 * self.sector(tx, ty)) + 28)
            ):
                self.hurt_actor(s, voices, i, damage)
        var px = Float32(word(s, 0)) / 256
        var py = Float32(word(s, 1)) / 256
        var damage = 128 - max(0, Int(max(abs(px - x), abs(py - y))) - 16)
        if damage > 0 and self.clear_path(
            s, x, y, z, px, py, Float32(self.height(s, 2 * self.sector(px, py)) + 28)
        ):
            self.hurt_player(s, voices, damage)

    def rocket_tick(self, s: I, voices: I):
        var a = self.player() + PLAYER_MISSILE
        var ttl = word(s, a + FLIGHT)
        if ttl == 0:
            return
        s[unsafe_offset=a + FLIGHT] -= 1
        var x = Float32(word(s, a + MX)) / 256
        var y = Float32(word(s, a + MY)) / 256
        var z = Float32(word(s, a + MZ)) / 256
        var nx = x + Float32(word(s, a + VX)) / 256
        var ny = y + Float32(word(s, a + VY)) / 256
        var nz = z + Float32(word(s, a + VZ)) / 256
        var sec = 2 * self.sector(nx, ny)
        var hit = (
            nz <= Float32(self.height(s, sec))
            or nz >= Float32(self.height(s, sec + 1))
            or not self.clear_path(s, x, y, z, nx, ny, nz)
        )
        for i in range(word(self.ix, 12)):
            var target = self.actor(i)
            if word(s, target + HP) <= 0 or word(s, target + MODE) >= DEAD:
                continue
            var tx = Float32(word(s, target + AX)) / 256
            var ty = Float32(word(s, target + AY)) / 256
            if (nx - tx) ** 2 + (ny - ty) ** 2 < 24 * 24:
                var bottom = Float32(self.height(s, 2 * self.sector(tx, ty)))
                if bottom <= nz <= bottom + 56 and not hit:
                    self.hurt_actor(s, voices, i, 20 * (1 + self.rand(s, 8)))
                    hit = True
                    break
        if hit:
            s[unsafe_offset=a + FLIGHT] = 0
            self.blast(s, voices, x, y, z)
            self.sound_at(s, voices, 32, x, y)
        else:
            s[unsafe_offset=a + MX] += s[unsafe_offset=a + VX]
            s[unsafe_offset=a + MY] += s[unsafe_offset=a + VY]
            s[unsafe_offset=a + MZ] += s[unsafe_offset=a + VZ]

    def attack(self, s: I, voices: I, x: Float32, y: Float32, angle: Float32) -> Int:
        var p = self.player()
        var gun = word(s, p + EQUIPPED)
        var melee = gun in (FIST, SAW)
        var slot = self.ammo_slot(gun)
        if not melee and word(s, slot) == 0:
            # Prefer a stocked firearm when the equipped weapon runs dry.
            for index in range(6):
                var candidate = (
                    CHAINGUN if index
                    == 0 else SHOTGUN if index
                    == 1 else PISTOL if index
                    == 2 else SAW if index
                    == 3 else LAUNCHER if index
                    == 4 else FIST
                )
                if word(s, p + WEAPONS) & (1 << candidate) and (
                    candidate in (FIST, SAW) or word(s, self.ammo_slot(candidate)) > 0
                ):
                    s[unsafe_offset=p + EQUIPPED] = Int32(candidate)
                    break
            return -1
        var ca = cos(angle)
        var sn = sin(angle)
        if gun == LAUNCHER:
            var a = p + PLAYER_MISSILE
            if word(s, a + FLIGHT):
                return -1
            s[unsafe_offset=a + MX] = Int32((x + ca * 16) * 256)
            s[unsafe_offset=a + MY] = Int32((y + sn * 16) * 256)
            s[unsafe_offset=a + MZ] = Int32((self.height(s, 2 * self.sector(x, y)) + 32) * 256)
            s[unsafe_offset=a + VX] = Int32(ca * 20 * 256)
            s[unsafe_offset=a + VY] = Int32(sn * 20 * 256)
            s[unsafe_offset=a + VZ] = 0
            s[unsafe_offset=a + FLIGHT] = 175
        elif gun == SHOTGUN:
            for _ in range(7):
                var spread = angle + Float32(self.rand(s, 257) - 128) * 0.00075
                self.shoot(s, voices, x, y, cos(spread), sin(spread))
        else:
            self.shoot(s, voices, x, y, ca, sn, 64 if melee else 2048, melee)
        if not melee:
            s[unsafe_offset=slot] -= 1
        s[unsafe_offset=p + REFIRE] = Int32(
            35 if gun
            == SHOTGUN else 4 if gun
            in (CHAINGUN, SAW) else 20 if gun
            in (FIST, LAUNCHER) else 14
        )
        s[unsafe_offset=8] = 6
        return (
            24 if gun
            == SHOTGUN else 31 if gun
            == LAUNCHER else 30 if gun
            == SAW else 33 if gun
            == FIST else 10
        )

    def monster_shot(
        self,
        s: I,
        voices: I,
        shooter: Int,
        x: Float32,
        y: Float32,
        z: Float32,
        bearing: Float32,
        slope: Float32,
    ):
        var spread = Float32(self.rand(s, 256) - self.rand(s, 256)) * 0.0015339808
        if word(s, self.player() + INVIS) and word(s, self.actor(shooter) + TARGET) == 0:
            spread *= 4
        var ca = cos(bearing + spread)
        var sn = sin(bearing + spread)
        var nearest = Float32(2048)
        var victim = -2
        for j in range(-1, word(self.ix, 12)):
            if j == shooter:
                continue
            var tx = Float32(word(s, 0)) / 256
            var ty = Float32(word(s, 1)) / 256
            var radius = Float32(16)
            if j >= 0:
                var a = self.actor(j)
                if word(s, a + MODE) >= DEAD or word(s, a + HP) <= 0:
                    continue
                tx = Float32(word(s, a + AX)) / 256
                ty = Float32(word(s, a + AY)) / 256
                radius = 20
            var depth = (tx - x) * ca + (ty - y) * sn
            if depth <= 0 or depth >= nearest or abs((tx - x) * sn - (ty - y) * ca) > radius:
                continue
            var bottom = Float32(self.height(s, 2 * self.sector(tx, ty)))
            var impact = z + slope * depth
            if bottom <= impact <= bottom + 56 and self.clear_path(
                s, x, y, z, x + ca * depth, y + sn * depth, impact
            ):
                nearest = depth
                victim = j
        if victim == -1:
            self.hurt_player(s, voices, 3 * (1 + self.rand(s, 5)))
        elif victim >= 0:
            self.hurt_actor(s, voices, victim, 3 * (1 + self.rand(s, 5)), shooter)

    def actors_tick(self, s: I, voices: I, fired: Bool):
        var px = Float32(word(s, 0)) / 256
        var py = Float32(word(s, 1)) / 256
        var pz = self.feet(s)
        var heard = external_call["cl_sound_sectors", I]()
        if fired:
            self.sound_reach(s, self.sector(px, py), heard)
        var tic = word(s, 7)
        for i in range(word(self.ix, 12)):
            var a = self.actor(i)
            var mode = word(s, a + MODE)
            if mode == REMOVED:
                continue
            var x = Float32(word(s, a + AX)) / 256
            var y = Float32(word(s, a + AY)) / 256
            var dx = px - x
            var dy = py - y
            var dist2 = dx * dx + dy * dy
            var t = self.sprite(i)
            var kind = word(self.ix, t + 5)
            if word(s, a + FLIGHT) > 0:
                var mx = Float32(word(s, a + MX)) / 256
                var my = Float32(word(s, a + MY)) / 256
                var mz = Float32(word(s, a + MZ)) / 256
                var nx = mx + Float32(word(s, a + VX)) / 256
                var ny = my + Float32(word(s, a + VY)) / 256
                var nz = mz + Float32(word(s, a + VZ)) / 256
                var sector = 2 * self.sector(nx, ny)
                var hit_player = (
                    (nx - px) ** 2 + (ny - py) ** 2 < 22 * 22 and nz >= pz and nz <= pz + 56
                )
                if (
                    hit_player
                    or nz <= Float32(self.height(s, sector))
                    or nz >= Float32(self.height(s, sector + 1))
                    or not self.clear_path(s, mx, my, mz, nx, ny, nz)
                ):
                    if hit_player:
                        self.hurt_player(
                            s, voices, (1 + self.rand(s, 8)) * (8 if kind == 3003 else 3)
                        )
                    s[unsafe_offset=a + FLIGHT] = 0
                    self.sound_at(s, voices, 20, nx, ny)
                else:
                    s[unsafe_offset=a + MX] += s[unsafe_offset=a + VX]
                    s[unsafe_offset=a + MY] += s[unsafe_offset=a + VY]
                    s[unsafe_offset=a + MZ] += s[unsafe_offset=a + VZ]
                    s[unsafe_offset=a + FLIGHT] -= 1
            if word(s, a + TIMER) > 0:
                s[unsafe_offset=a + TIMER] -= 1
            if kind == 2035:
                if mode == DEAD and word(s, a + TIMER) == 10:
                    self.blast(s, voices, x, y, Float32(self.height(s, 2 * self.sector(x, y)) + 24))
                if mode == DEAD and not word(s, a + TIMER):
                    s[unsafe_offset=a + MODE] = REMOVED
                continue
            if mode == DEAD and word(s, self.player() + SKILL) == 5:
                s[unsafe_offset=a + CORPSE_AGE] = Int32(min(100000, word(s, a + CORPSE_AGE) + 1))
                if word(s, a + CORPSE_AGE) >= 12 * 35 and not (tic & 31) and self.rand(s, 256) <= 4:
                    var sx = Float32(word(self.ix, t))
                    var sy = Float32(word(self.ix, t + 1))
                    if (sx - px) ** 2 + (sy - py) ** 2 > 32 * 32 and not self.occupied(
                        s, sx, sy, i
                    ):
                        s[unsafe_offset=a + AX] = Int32(sx * 256)
                        s[unsafe_offset=a + AY] = Int32(sy * 256)
                        s[unsafe_offset=a + FACING] = Int32(
                            (word(self.ix, t + 6) * 4096 // 360) & 4095
                        )
                        s[unsafe_offset=a + HP] = Int32(hit_points(kind))
                        s[unsafe_offset=a + MODE] = ASLEEP
                        s[unsafe_offset=a + TARGET] = 0
                        s[unsafe_offset=a + CORPSE_AGE] = 0
                        s[unsafe_offset=a + DROP] = 0
                        continue
            if mode == DEAD or hit_points(kind) == 0:
                var dropped = word(s, a + DROP) != 0
                if mode == DEAD and not dropped:
                    continue
                if (
                    dist2 < 32 * 32
                    and Float32(-8) <= Float32(self.height(s, 2 * self.sector(x, y))) - pz <= 56
                ):
                    var item = (2001 if kind == 9 else 2007) if dropped else kind
                    if self.acquire(s, item, dropped):
                        if dropped:
                            s[unsafe_offset=a + DROP] = 0
                        else:
                            s[unsafe_offset=a + MODE] = REMOVED
                        start_sound(self, voices, 34 if item in (2001, 2002, 2003, 2005) else 13)
                continue
            if word(s, self.player() + HEALTH) == 0:
                continue
            var timer = word(s, a + TIMER)
            if mode == ASLEEP and not fired and (tic + i) % 8 != 0:
                continue
            if mode in (AIM, RECOVER, PAIN) and timer:
                continue
            if mode == CHASE and (tic + i) % 3 != 0:
                continue
            var floor_z = Float32(self.height(s, 2 * self.sector(x, y)))
            var target = word(s, a + TARGET) - 1
            var tx = px
            var ty = py
            var tz = pz
            if target >= 0:
                var foe = self.actor(target)
                if word(s, foe + HP) <= 0 or word(s, foe + MODE) >= DEAD:
                    s[unsafe_offset=a + TARGET] = 0
                    target = -1
                else:
                    tx = Float32(word(s, foe + AX)) / 256
                    ty = Float32(word(s, foe + AY)) / 256
                    tz = Float32(self.height(s, 2 * self.sector(tx, ty)))
                    dx = tx - x
                    dy = ty - y
                    dist2 = dx * dx + dy * dy
            var sight = self.clear_path(s, x, y, floor_z + 36, tx, ty, tz + 32)
            var toward = heading(dx, dy)
            if mode == ASLEEP:
                var facing = Float32(word(s, a + FACING)) * 0.0015339808
                var hears = (
                    fired and not (word(self.ix, t + 7) & 8) and word(heard, self.sector(x, y)) < 2
                )
                if not hears and (
                    not sight or (dist2 > 64 * 64 and dx * cos(facing) + dy * sin(facing) < 0)
                ):
                    continue
                s[unsafe_offset=a + MODE] = CHASE
                self.sound_at(
                    s,
                    voices,
                    15 if kind
                    == 3001 else 25 if kind
                    in (3002, 58) else 28 if kind
                    == 3003 else 14,
                    x,
                    y,
                )
                continue
            s[unsafe_offset=a + FACING] = Int32(toward)
            var distance = max(Float32(1), sqrt(dist2))
            if mode == AIM:
                if sight:
                    if kind in (3004, 9):
                        for _ in range(3 if kind == 9 else 1):
                            self.monster_shot(
                                s,
                                voices,
                                i,
                                x,
                                y,
                                floor_z + 36,
                                Float32(toward) * 0.0015339808,
                                (tz - floor_z - 4) / distance,
                            )
                        self.sound_at(s, voices, 24 if kind == 9 else 10, x, y)
                    elif distance <= 64:
                        var damage = (1 + self.rand(s, 8)) * (8 if kind == 3003 else 3)
                        if target < 0:
                            self.hurt_player(s, voices, damage)
                        else:
                            self.hurt_actor(s, voices, target, damage, i)
                        self.sound_at(s, voices, 26 if kind in (3002, 58) else 21, x, y)
                    elif kind in (3001, 3003) and word(s, a + FLIGHT) == 0:
                        var speed = Float32(
                            20 if word(s, self.player() + SKILL)
                            == 5 else 15 if kind
                            == 3003 else 10
                        )
                        s[unsafe_offset=a + MX] = Int32(x * 256)
                        s[unsafe_offset=a + MY] = Int32(y * 256)
                        s[unsafe_offset=a + MZ] = Int32((floor_z + 32) * 256)
                        s[unsafe_offset=a + VX] = Int32(dx / distance * speed * 256)
                        s[unsafe_offset=a + VY] = Int32(dy / distance * speed * 256)
                        if target < 0 and word(s, self.player() + INVIS):
                            var jitter = (
                                Float32(self.rand(s, 256) - self.rand(s, 256)) * 0.0030679616
                            )
                            var bearing = Float32(toward) * 0.0015339808 + jitter
                            s[unsafe_offset=a + VX] = Int32(cos(bearing) * speed * 256)
                            s[unsafe_offset=a + VY] = Int32(sin(bearing) * speed * 256)
                        s[unsafe_offset=a + VZ] = Int32((tz - floor_z) / distance * speed * 256)
                        s[unsafe_offset=a + FLIGHT] = 140
                        self.sound_at(s, voices, 19, x, y)
                s[unsafe_offset=a + MODE] = RECOVER
                s[unsafe_offset=a + TIMER] = Int32(12 + self.rand(s, 16))
                continue
            s[unsafe_offset=a + MODE] = CHASE
            if sight and (
                distance < 60
                or (kind not in (3002, 58) and distance < 1000 and self.rand(s, 12) == 0)
            ):
                s[unsafe_offset=a + MODE] = AIM
                s[unsafe_offset=a + TIMER] = 8
                continue
            var speed = Float32(9 if kind in (3002, 58) else 6)
            if kind in (3002, 58) and word(s, self.player() + SKILL) == 5:
                speed *= 2
            var nx = x + dx / distance * speed
            var ny = y + dy / distance * speed
            if (
                distance > 30
                and not self.occupied(s, nx, y, i)
                and self.can_move(s, nx, y, Int(floor_z), x, y)
            ):
                s[unsafe_offset=a + AX] = Int32(nx * 256)
                x = nx
            if (
                distance > 30
                and not self.occupied(s, x, ny, i)
                and self.can_move(s, x, ny, Int(floor_z), x, y)
            ):
                s[unsafe_offset=a + AY] = Int32(ny * 256)

    def tick(
        self, s: I, forward: Int, strafe: Int, turn: Int, use: Bool, fire: Bool, voices: I
    ) -> Int:
        if word(s, 6) or word(s, self.player() + HEALTH) == 0:
            return -1
        s[unsafe_offset=7] = Int32((word(s, 7) + 1) & 0x3FFFFFFF)
        s[unsafe_offset=8] = Int32(max(0, word(s, 8) - 1))
        s[unsafe_offset=10] = Int32(max(0, word(s, 10) - 1))
        s[unsafe_offset=2] = Int32((word(s, 2) + turn) & 4095)
        var angle = Float32(word(s, 2)) * 0.0015339808
        var c = cos(angle)
        var sn = sin(angle)
        var x = Float32(word(s, 0)) / 256
        var y = Float32(word(s, 1)) / 256
        var speed = Float32(2.12) if forward != 0 and strafe != 0 else Float32(3)
        var nx = x + speed * (Float32(forward) * c + Float32(strafe) * sn)
        var ny = y + speed * (Float32(forward) * sn - Float32(strafe) * c)
        var oldfloor = Int(self.feet(s))
        if not word(s, self.player() + HEIGHT_READY):
            self.gravity(s, self.sector(x, y))
        if nx != x and not self.occupied(s, nx, y, -1) and self.can_move(s, nx, y, oldfloor, x, y):
            s[unsafe_offset=0] = Int32(nx * 256)
        if (
            ny != y
            and not self.occupied(s, Float32(word(s, 0)) / 256, ny, -1)
            and self.can_move(
                s, Float32(word(s, 0)) / 256, ny, oldfloor, Float32(word(s, 0)) / 256, y
            )
        ):
            s[unsafe_offset=1] = Int32(ny * 256)
        var sound = self.cross_lines(s, x, y, Float32(word(s, 0)) / 256, Float32(word(s, 1)) / 256)
        var cooldown = self.player() + REFIRE
        if word(s, cooldown) > 0:
            s[unsafe_offset=cooldown] -= 1
        self.rocket_tick(s, voices)
        var fired = False
        if fire and word(s, cooldown) == 0:
            var shot = self.attack(
                s, voices, Float32(word(s, 0)) / 256, Float32(word(s, 1)) / 256, angle
            )
            if shot >= 0:
                sound = shot
                fired = True
        if use or fired:
            var nearest = Float32(66 if use else 2048)
            var hit = -1
            for i in range(self.length(1) // 14):
                var l = self.lump(1) + 14 * i
                var ax, ay, bx, by = self.endpoints(i)
                var dx = bx - ax
                var dy = by - ay
                var det = c * dy - sn * dx
                if abs(det) < 0.001:
                    continue
                var dist = ((ax - x) * dy - (ay - y) * dx) / det
                var u = ((ax - x) * sn - (ay - y) * c) / det
                if dist >= 0 and dist < nearest and u >= 0 and u <= 1:
                    if w(self.wad, l + 6) or w(self.wad, l + 12) == 65535:
                        nearest = dist
                        hit = l
            if hit >= 0:
                var effect = self.activate(s, (hit - self.lump(1)) // 14, 0 if use else 2)
                if effect >= 0:
                    sound = effect
        var current_sec = self.sector(Float32(word(s, 0)) / 256, Float32(word(s, 1)) / 256)
        self.advance_movers(s, current_sec)
        self.gravity(s, current_sec)
        self.discover(s, Float32(word(s, 0)) / 256, Float32(word(s, 1)) / 256)
        var sector_type = w(self.wad, self.lump(3) + 26 * current_sec + 22)
        if word(s, self.mover(current_sec) + FOUND_SECRET) >> 1:
            sector_type = 0
        var suit = self.player() + SUIT
        if self.feet(s) > Float32(self.height(s, 2 * current_sec)):
            sector_type = 0
        for i in range(3):
            var slot = self.player() + (SUIT if i == 0 else INVIS if i == 1 else LIGHT_POWER)
            if word(s, slot) > 0:
                s[unsafe_offset=slot] -= 1
        if sector_type == 9 and not (word(s, self.mover(current_sec) + FOUND_SECRET) & 1):
            s[unsafe_offset=self.player() + SECRETS] += 1
            s[unsafe_offset=self.mover(current_sec) + FOUND_SECRET] |= 1
        if (word(s, 7) & 31) == 0 and sector_type in (4, 5, 7, 11, 16):
            if (
                word(s, suit) == 0
                or sector_type == 11
                or (sector_type in (4, 16) and self.rand(s, 256) < 5)
            ):
                self.hurt_player(
                    s, voices, 5 if sector_type == 7 else 10 if sector_type == 5 else 20
                )
        self.actors_tick(s, voices, fired)
        if sector_type == 11 and word(s, self.player() + HEALTH) <= 10:
            s[unsafe_offset=6] = 1
        return sound


def screen(p: V) -> V:
    var iz = 1 / p[2]
    return V(160 + 160 * p[0] * iz, 85 - 133.33333 * p[1] * iz, iz, p[3] * iz, p[4] * iz, 0, 0, 0)


def side(a: V, b: V, x: Float32, y: Float32) -> Float32:
    return (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])


def raster(a0: V, b0: V, c0: V, tex: P, tw: Int, th: Int, pixels: P, depth: F, style: Int):
    var sky = external_call["cl_sky_columns", I]()
    var a = screen(a0)
    var b = screen(b0)
    var c = screen(c0)
    var area = side(a, b, c[0], c[1])
    if abs(area) < 0.002:
        return
    if area < 0:
        var t = b
        b = c
        c = t
        area = -area
    var x0 = max(0, Int(min(a[0], min(b[0], c[0]))))
    var x1 = min(319, Int(max(a[0], max(b[0], c[0]))) + 1)
    var y0 = max(0, Int(min(a[1], min(b[1], c[1]))))
    var y1 = min(177, Int(max(a[1], max(b[1], c[1]))) + 1)
    if x0 > x1 or y0 > y1:
        return
    var d0 = b[1] - c[1]
    var d1 = c[1] - a[1]
    var d2 = a[1] - b[1]
    for y in range(y0, y1 + 1):
        var e0 = side(b, c, Float32(x0) + 0.5, Float32(y) + 0.5)
        var e1 = side(c, a, Float32(x0) + 0.5, Float32(y) + 0.5)
        var e2 = side(a, b, Float32(x0) + 0.5, Float32(y) + 0.5)
        for x in range(x0, x1 + 1):
            if e0 >= -0.001 and e1 >= -0.001 and e2 >= -0.001:
                var offset = y * 320 + x
                var z = a[2] * e0 + b[2] * e1 + c[2] * e2
                if z > 0 and z > depth[unsafe_offset=offset] * area:
                    var u = Int(floor((a[3] * e0 + b[3] * e1 + c[3] * e2) / z))
                    var v = Int(floor((a[4] * e0 + b[4] * e1 + c[4] * e2) / z))
                    if style == 1:
                        u = word(sky, x)
                        v = min(th - 1, max(0, 100 + y - 85))
                    var color = tex[unsafe_offset=((v % th + th) % th) * tw + (u % tw + tw) % tw]
                    if color and (style < 2 or (x + y + style) % 3 != 0):
                        if style >= 2:
                            color = UInt32(0xFF000000) | (
                                (pixels[unsafe_offset=offset] >> 1) & UInt32(0x007F7F7F)
                            )
                        pixels[unsafe_offset=offset] = color
                        depth[unsafe_offset=offset] = z / area
            e0 += d0
            e1 += d1
            e2 += d2


def cross_near(a: V, b: V) -> V:
    return a + (b - a) * ((1 - a[2]) / (b[2] - a[2]))


def clipped(a: V, b: V, c: V, tex: P, wid: Int, ht: Int, p: P, z: F, style: Int):
    if a[2] < 1:
        if b[2] < 1:
            if c[2] >= 1:
                raster(c, cross_near(c, a), cross_near(c, b), tex, wid, ht, p, z, style)
        elif c[2] < 1:
            raster(b, cross_near(b, c), cross_near(b, a), tex, wid, ht, p, z, style)
        else:
            var ba = cross_near(b, a)
            var ca = cross_near(c, a)
            raster(b, c, ca, tex, wid, ht, p, z, style)
            raster(b, ca, ba, tex, wid, ht, p, z, style)
    elif b[2] < 1:
        if c[2] < 1:
            raster(a, cross_near(a, b), cross_near(a, c), tex, wid, ht, p, z, style)
        else:
            var ab = cross_near(a, b)
            var cb = cross_near(c, b)
            raster(a, ab, cb, tex, wid, ht, p, z, style)
            raster(a, cb, c, tex, wid, ht, p, z, style)
    elif c[2] < 1:
        var ac = cross_near(a, c)
        var bc = cross_near(b, c)
        raster(a, b, bc, tex, wid, ht, p, z, style)
        raster(a, bc, ac, tex, wid, ht, p, z, style)
    else:
        raster(a, b, c, tex, wid, ht, p, z, style)


def camera(v: V, eye: V) -> V:
    var dx = v[0] - eye[0]
    var dy = v[1] - eye[1]
    return point(dx * eye[4] - dy * eye[3], v[2] - eye[2], dx * eye[3] + dy * eye[4], v[3], v[4])


def submit(
    m: Hangar, eye: V, a: V, b: V, c: V, mat: Int, light: Int, p: P, z: F, gpu: Bool, style: Int = 0
):
    var ca = camera(a, eye)
    var cb = camera(b, eye)
    var cc = camera(c, eye)
    if max(ca[2], max(cb[2], cc[2])) < 1:
        return
    if (
        min(ca[0] - ca[2], min(cb[0] - cb[2], cc[0] - cc[2])) > 0
        or max(ca[0] + ca[2], max(cb[0] + cb[2], cc[0] + cc[2])) < 0
    ):
        return
    var tw = m.desc(mat, 0)
    var th = m.desc(mat, 1)
    if gpu:
        var id = Int32(mat * 4 + light)
        _ = external_call["cl_vertex", Int32](
            id, Int32(style), a[0], a[1], a[2] - eye[2] + 40, a[3] / Float32(tw), a[4] / Float32(th)
        )
        _ = external_call["cl_vertex", Int32](
            id, Int32(style), b[0], b[1], b[2] - eye[2] + 40, b[3] / Float32(tw), b[4] / Float32(th)
        )
        _ = external_call["cl_vertex", Int32](
            id, Int32(style), c[0], c[1], c[2] - eye[2] + 40, c[3] / Float32(tw), c[4] / Float32(th)
        )
    else:
        clipped(ca, cb, cc, m.tex.unsafe_offset(m.source(mat, light)), tw, th, p, z, style)


def billboard(
    m: Hangar,
    s: I,
    eye: V,
    x: Float32,
    y: Float32,
    base_z: Float32,
    mat: Int,
    left: Int,
    top: Int,
    flip: Bool,
    p: P,
    z: F,
    gpu: Bool,
    style: Int = 0,
    fullbright: Bool = False,
):
    var ca = eye[3]
    var sn = eye[4]
    var sec = m.sector(x, y)
    var width = m.desc(mat, 0)
    var height = m.desc(mat, 1)
    var hi = base_z + Float32(top)
    var lo = hi - Float32(height)
    var u0 = Float32(width if flip else 0)
    var u1 = Float32(0 if flip else width)
    var x0 = x - sn * Float32(left)
    var y0 = y + ca * Float32(left)
    var x1 = x0 + sn * Float32(width)
    var y1 = y0 - ca * Float32(width)
    var a = point(x0, y0, lo, u0, Float32(height))
    var b = point(x1, y1, lo, u1, Float32(height))
    var c = point(x1, y1, hi, u1, 0)
    var d = point(x0, y0, hi, u0, 0)
    var light = 0 if fullbright else m.shade(s, sec)
    submit(m, eye, a, b, c, mat, light, p, z, gpu, style)
    submit(m, eye, a, c, d, mat, light, p, z, gpu, style)


def compose(m: Hangar, s: I, p: P, z: F, gpu: Bool):
    var px = Float32(word(s, 0)) / 256
    var py = Float32(word(s, 1)) / 256
    var angle = Float32(word(s, 2)) * 0.0015339808
    var ca = cos(angle)
    var sn = sin(angle)
    var eye = point(px, py, m.feet(s) + 40, ca, sn)
    if gpu:
        _ = external_call["sw_camera", Int32](px, py, angle)
    for i in range(320 * 200):
        p[unsafe_offset=i] = 0 if gpu else UInt32(0xFF181820)
        z[unsafe_offset=i] = 0
    var sky_mat = word(m.ix, word(m.layout, 8))
    if not gpu and sky_mat >= 0:
        var cols = external_call["cl_sky_columns", I]()
        for col in range(320):
            cols[unsafe_offset=col] = Int32(
                floor((atan2(Float32(col) + 0.5 - 160, Float32(160)) - angle) * 162.97466)
            )
    var start = 46 + 5 * word(m.ix, 9) + 4 * word(m.ix, 10)
    for t in range(word(m.ix, 11)):
        var k = start + 17 * t
        var line = word(m.ix, word(m.layout, 7) + t)
        var scroll = Float32(word(s, 7) % 1024) if line >= 0 and w(
            m.wad, m.lump(1) + line * 14 + 6
        ) == 48 else Float32(0)
        var mat = m.animated(s, word(m.ix, k), line)
        var sec = word(m.ix, k + 1)
        var flat_source = word(s, m.mover(sec) + FOUND_SECRET) >> 1
        if line < 0 and not (word(m.ix, k + 4) & 1) and 0 < flat_source <= m.sectors():
            var flat_table = word(m.layout, 9)
            mat = m.animated(s, word(m.ix, flat_table + flat_source - 1), -1)
        var light = m.shade(s, sec)
        var vertical = m.f[unsafe_offset=k + 6] >= 8192
        if vertical:
            var ax = m.f[unsafe_offset=k + 2]
            var ay = m.f[unsafe_offset=k + 3]
            var bx = m.f[unsafe_offset=k + 7]
            var by = m.f[unsafe_offset=k + 8]
            if (bx - ax) * (py - ay) - (by - ay) * (px - ax) > 0:
                continue
            if m.height(s, word(m.ix, k + 14)) <= m.height(s, word(m.ix, k + 4)):
                continue
        else:
            var h = m.height(s, word(m.ix, k + 4))
            if (word(m.ix, k + 4) & 1 and eye[2] > Float32(h)) or (
                not (word(m.ix, k + 4) & 1) and eye[2] < Float32(h)
            ):
                continue

        def vertex(i: Int) {m, s, k, vertical, scroll} -> V:
            var j = k + 2 + i * 5
            var h = Float32(m.height(s, word(m.ix, j + 2)))
            var v = m.f[unsafe_offset=j + 4]
            if vertical:
                var encoded = Int(v)
                v = Float32(m.height(s, (encoded // 8192) - 1) + (encoded % 8192) - 4096) - h
            return point(
                m.f[unsafe_offset=j],
                m.f[unsafe_offset=j + 1],
                h,
                m.f[unsafe_offset=j + 3] + scroll,
                v,
            )

        submit(
            m,
            eye,
            vertex(0),
            vertex(1),
            vertex(2),
            mat,
            0 if mat == sky_mat else light,
            p,
            z,
            gpu,
            Int(mat == sky_mat),
        )
    for i in range(word(m.ix, 12)):
        var a = m.actor(i)
        var mode = word(s, a + MODE)
        if mode == REMOVED:
            continue
        var k = m.sprite(i)
        var x = Float32(word(s, a + AX)) / 256
        var y = Float32(word(s, a + AY)) / 256
        var mat = word(m.ix, k + 2)
        var left = word(m.ix, k + 3)
        var top = word(m.ix, k + 4)
        if word(m.ix, k + 5) == 2024:
            mat += (word(s, 7) // 6) % 4
        var group = word(m.ix, k + 8)
        var flip = False
        if group >= 0:
            var timer = word(s, a + TIMER)
            var letter = 0
            if mode == CHASE:
                letter = (word(s, 7) // 4 + i) % 4
            elif mode == AIM:
                letter = 4 if timer >= 4 else 5
            elif mode == RECOVER:
                letter = 5 if group <= 1 else 6
            elif mode == PAIN:
                letter = 6 if group <= 1 else 7
            elif mode == DEAD:
                var first = 7 if group <= 1 else 8
                var last = 11 if group <= 1 else 12 if group == 2 else 13 if group == 3 else 14
                letter = min(last, first + (25 - timer) // 4)
            var view = ((heading(px - x, py - y) - word(s, a + FACING) + 256) & 4095) // 512
            var rec = word(m.layout, 0) + 4 * ((group * 15 + letter) * 8 + view)
            if word(m.ix, rec) >= 0:
                mat = word(m.ix, rec)
                left = word(m.ix, rec + 1)
                top = word(m.ix, rec + 2)
                flip = word(m.ix, rec + 3) != 0
        if word(m.ix, k + 5) == 2035 and mode == DEAD:
            mat = word(m.ix, word(m.layout, 3) + 5 + min(4, (15 - word(s, a + TIMER)) // 3))
            left = m.desc(mat, 0) // 2
            top = m.desc(mat, 1)
        var floor_z = Float32(m.height(s, 2 * m.sector(x, y)))
        billboard(
            m,
            s,
            eye,
            x,
            y,
            floor_z,
            mat,
            left,
            top,
            flip,
            p,
            z,
            gpu,
            2 + word(s, 7) % 2 if word(m.ix, k + 5) == 58 else 0,
            word(m.ix, k + 5) == 2024,
        )
        if word(s, a + DROP):
            var clip_mat = word(m.ix, word(m.layout, 3) + 4) if word(m.ix, k + 5) == 9 else word(
                m.ix, m.hud_table() + 21
            )
            billboard(
                m,
                s,
                eye,
                x + 3,
                y + 3,
                floor_z,
                clip_mat,
                m.desc(clip_mat, 0) // 2,
                m.desc(clip_mat, 1),
                False,
                p,
                z,
                gpu,
            )
        if word(s, a + FLIGHT) > 0:
            var missile_group = 6 if group == 4 else 5
            var rec = word(m.layout, 0) + 4 * ((missile_group * 15 + (word(s, 7) // 4) % 2) * 8)
            var missile = word(m.ix, rec)
            if missile >= 0:
                billboard(
                    m,
                    s,
                    eye,
                    Float32(word(s, a + MX)) / 256,
                    Float32(word(s, a + MY)) / 256,
                    Float32(word(s, a + MZ)) / 256,
                    missile,
                    word(m.ix, rec + 1),
                    word(m.ix, rec + 2),
                    False,
                    p,
                    z,
                    gpu,
                )
    var rocket = m.player() + PLAYER_MISSILE
    if word(s, rocket + FLIGHT):
        var mat = word(m.ix, word(m.layout, 3))
        billboard(
            m,
            s,
            eye,
            Float32(word(s, rocket + MX)) / 256,
            Float32(word(s, rocket + MY)) / 256,
            Float32(word(s, rocket + MZ)) / 256,
            mat,
            m.desc(mat, 0) // 2,
            m.desc(mat, 1) // 2,
            False,
            p,
            z,
            gpu,
        )
    if gpu:
        _ = external_call["cl_flush", Int32]()


def blit(m: Hangar, p: P, mat: Int, x: Int, y: Int, shadow_phase: Int = -1):
    var tw = m.desc(mat, 0)
    var th = m.desc(mat, 1)
    var base = m.source(mat, 0)
    for row in range(max(0, -y), min(th, 200 - y)):
        for col in range(max(0, -x), min(tw, 320 - x)):
            var color = m.tex[unsafe_offset=base + row * tw + col]
            if color:
                if shadow_phase >= 0:
                    if (row + col + shadow_phase) % 3:
                        continue
                    color = 0xFF333034
                p[unsafe_offset=(y + row) * 320 + x + col] = color


def overlay(m: Hangar, p: P, s: I, automap: Bool = False):
    var firing = word(s, 8) > 2
    var equip = word(s, m.player() + EQUIPPED)
    var art = m.weapon_art() + 4 * equip
    if not automap:
        var gun = word(m.ix, art + (1 if firing else 2 if word(s, 8) > 0 else 0))
        var width = m.desc(gun, 0)
        var remaining = word(s, m.player() + INVIS)
        var shadow = word(s, 7) % 3 if remaining > 128 or (remaining & 8) != 0 else -1
        blit(m, p, gun, 160 - width // 2, 168 - m.desc(gun, 1), shadow)
        if firing and word(m.ix, art + 3) >= 0:
            var flash = word(m.ix, art + 3)
            blit(
                m,
                p,
                flash,
                160 - m.desc(flash, 0) // 2,
                168 - m.desc(gun, 1) - m.desc(flash, 1) + 4,
                shadow,
            )
    blit(m, p, word(m.ix, 44), 0, 168)
    var face = min(4, max(0, (100 - word(s, m.player() + HEALTH)) // 20))
    blit(m, p, word(m.ix, word(m.layout, 3) + 13 + face), 144, 169)
    for key in range(3):
        if word(s, m.player() + KEYS) & (1 << key):
            blit(m, p, word(m.ix, word(m.layout, 3) + 10 + key), 239, 171 + key * 10)
    var table = m.hud_table()

    def number(value: Int, x: Int, y: Int, small: Bool) {m, p, table}:
        var n = value
        var cursor = x
        while True:
            var mat = word(m.ix, table + (11 if small else 0) + n % 10)
            cursor -= m.desc(mat, 0)
            blit(m, p, mat, cursor, y)
            n = n // 10
            if n == 0:
                break

    if equip not in (FIST, SAW):
        number(word(s, m.ammo_slot(equip)), 44, 171, False)
    number(word(s, m.player() + HEALTH), 90, 171, False)
    number(word(s, m.player() + ARMOR), 220, 171, False)
    blit(m, p, word(m.ix, table + 10), 90, 171)
    blit(m, p, word(m.ix, table + 10), 220, 171)
    for i in range(4):
        number(
            word(s, 5) if i
            == 0 else word(s, m.player() + SHELLS) if i
            == 1 else word(s, m.player() + ROCKETS) if i
            == 3 else 0,
            288,
            173 + 6 * i,
            True,
        )
        number(200 if i == 0 else 50 if i == 1 or i == 3 else 300, 314, 173 + 6 * i, True)


# Four independent DMX voices. Store offset, length, source rate and output cursor.
def start_sound(m: Hangar, voices: I, sound: Int, left: Float32 = 1, right: Float32 = 1):
    var o = m.lump(sound)
    var length = dw(m.wad, o + 4) - 32
    var rate = w(m.wad, o + 2)
    if w(m.wad, o) != 3 or length <= 0 or length + 40 > m.length(sound) or rate <= 0:
        return
    var slot = word(voices, 48) % 8
    voices[unsafe_offset=48] = Int32((slot + 1) % 8)
    voices[unsafe_offset=6 * slot] = Int32(o + 24)
    voices[unsafe_offset=6 * slot + 1] = Int32(length)
    voices[unsafe_offset=6 * slot + 2] = Int32(rate)
    voices[unsafe_offset=6 * slot + 3] = 0
    voices[unsafe_offset=6 * slot + 4] = Int32(left * 256)
    voices[unsafe_offset=6 * slot + 5] = Int32(right * 256)
    _ = external_call["cl_sound_event", Int32](Int32(sound))


def check_tracks(m: Hangar) -> Bool:
    var music = word(m.layout, 4)
    var seq = soundtrack.Sequencer(
        m.wad,
        word(m.ix, music),
        external_call["cl_music_state", I](),
        external_call["cl_music_synth", F](),
        external_call["cl_music_wave", F](),
    )
    var pcm = external_call["sw_audio_buffer", F]()
    for track in range(1, 5):
        var peak = Float32(0)
        var energy = Float32(0)
        for _ in range(128):
            for i in range(512):
                pcm[unsafe_offset=i] = 0
            seq.mix(word(m.ix, music + 2 * track), word(m.ix, music + 2 * track + 1), pcm, 512)
            for i in range(512):
                var value = pcm[unsafe_offset=i]
                peak = max(peak, abs(value))
                energy += value * value
        if not (peak > 0.005 and peak < 2 and energy > 1):
            return False
    return True


def pump_audio(m: Hangar, voices: I, track: Int = 1, target: Int = 1536):
    var pcm = external_call["sw_audio_buffer", F]()
    var melody = external_call["cl_music_buffer", F]()
    var music = word(m.layout, 4)
    var sequence = soundtrack.Sequencer(
        m.wad,
        word(m.ix, music),
        external_call["cl_music_state", I](),
        external_call["cl_music_synth", F](),
        external_call["cl_music_wave", F](),
    )
    for _ in range((target + 511) // 512 + 1):
        if external_call["cl_need_audio", Int32](Int32(target)) == 0:
            return
        for i in range(512):
            melody[unsafe_offset=i] = 0
        sequence.mix(word(m.ix, music + track * 2), word(m.ix, music + track * 2 + 1), melody, 512)
        for i in range(512):
            pcm[unsafe_offset=2 * i] = melody[unsafe_offset=i]
            pcm[unsafe_offset=2 * i + 1] = melody[unsafe_offset=i]
        for slot in range(8):
            var k = 6 * slot
            var length = word(voices, k + 1)
            if not length:
                continue
            var cursor = word(voices, k + 3)
            var rate = word(voices, k + 2)
            var start = word(voices, k)
            var left = Float32(word(voices, k + 4)) * (0.23 / (128 * 256))
            var right = Float32(word(voices, k + 5)) * (0.23 / (128 * 256))
            for i in range(512):
                var index = (cursor + i) * rate // 22050
                if index >= length:
                    voices[unsafe_offset=k + 1] = 0
                    break
                var sample = Float32(rd(m.wad, start + index) - 128)
                pcm[unsafe_offset=2 * i] += sample * left
                pcm[unsafe_offset=2 * i + 1] += sample * right
            voices[unsafe_offset=k + 3] = Int32(cursor + 512)
        for i in range(1024):
            pcm[unsafe_offset=i] = max(Float32(-1), min(Float32(1), pcm[unsafe_offset=i]))
        _ = external_call["sw_audio", Int32](Int32(512))


def current_map() -> Hangar:
    return Hangar(
        external_call["cl_wad", B](),
        external_call["cl_ix", I](),
        external_call["cl_ix", F](),
        external_call["cl_texels", P](),
        external_call["cl_bases", I](),
        external_call["cl_layout", I](),
    )


def restore(mut m: Hangar, s: I, tmp: I, gpu: Bool = False) -> Bool:
    var layout = Int(external_call["cl_read_save", Int32](tmp))
    var map = layout & 255
    if map == 0:
        return False
    var sectors = Int(external_call["cl_saved_sectors", Int32](Int32(map)))
    var sprites = layout >> 8
    var player = 11 + sectors
    if not (0 <= word(tmp, 2) <= 4095 and 0 <= word(tmp, 5) <= 400):
        return False
    if not (0 <= word(tmp, player + HEALTH) <= 200 and 0 <= word(tmp, player + ARMOR) <= 200):
        return False
    if not (1 <= word(tmp, player + SKILL) <= 5 and 0 <= word(tmp, 6) <= 2):
        return False
    if not (0 <= word(tmp, player + EQUIPPED) <= SAW and 0 <= word(tmp, player + WEAPONS) <= 63):
        return False
    for sec in range(sectors):
        if not (-65535 <= word(tmp, 11 + sec) <= 65535):
            return False
    for i in range(sprites):
        var a = player + PLAYER_WORDS + i * 16
        if not (0 <= word(tmp, a + TARGET) <= sprites):
            return False
        if not (0 <= word(tmp, a + MODE) <= REMOVED and 0 <= word(tmp, a + TIMER) < 256):
            return False
        if not (0 <= word(tmp, a + FLIGHT) <= 140 and 0 <= word(tmp, a + FACING) < 4096):
            return False
    if map != Int(external_call["cl_map", Int32]()):
        if not external_call["cl_change_map", Int32](Int32(map)):
            return False
        m = current_map()
        m.decode(True)
        if gpu:
            m.upload(True)
    for k in range(m.state_size()):
        s[unsafe_offset=k] = tmp[unsafe_offset=k]
    m.spawn_actors(s, sprites)
    s[unsafe_offset=9] = 0
    s[unsafe_offset=10] = 0
    return True


def import_hangar(mut m: Hangar, s: I, tmp: I, gpu: Bool = False) -> Bool:
    if not external_call["cl_read_legacy", Int32](tmp):
        return False
    if not (0 <= word(tmp, 2) < 4096 and 0 <= word(tmp, 5) <= 50 and 0 <= word(tmp, 6) <= 1):
        return False
    if abs(Int64(word(tmp, 0))) > 4000 * 256 or abs(Int64(word(tmp, 1))) > 6000 * 256:
        return False
    for sec in range(85):
        if not (0 <= word(tmp, 11 + sec) <= 65535):
            return False
    if external_call["cl_map", Int32]() != 1:
        if not external_call["cl_change_map", Int32](Int32(1)):
            return False
        m = current_map()
        m.decode(True)
        if gpu:
            m.upload(True)
    m.spawn(s)
    for k in range(9):
        s[unsafe_offset=k] = tmp[unsafe_offset=k]
    for sec in range(85):
        var delta = min(word(tmp, 11 + sec), word(m.ix, m.stops() + sec))
        s[unsafe_offset=11 + sec] = Int32(delta)
        if delta > 0 and delta < word(m.ix, m.stops() + sec):
            var slot = m.mover(sec)
            s[unsafe_offset=slot + CEIL_SPEED] = 2
            s[unsafe_offset=slot + CEIL_GOAL] = Int32(
                signed(m.wad, m.lump(3) + 26 * sec + 2) + word(m.ix, m.stops() + sec)
            )
    return True


def campaign_step(
    mut m: Hangar,
    s: I,
    voices: I,
    forward: Int,
    strafe: Int,
    turn: Int,
    use: Bool,
    fire: Bool,
    gpu: Bool,
) -> Int:
    var won = word(s, 6)
    if not won:
        if word(s, m.player() + HEALTH) == 0 and use:
            m.spawn(s, word(s, m.player() + SKILL))
            return -1
        return m.tick(s, forward, strafe, turn, use, fire, voices)
    if not use:
        return -1
    var map = Int(external_call["cl_map", Int32]())
    var finale = map == 8
    var next_map = 1 if finale else 9 if won == 2 else 4 if map == 9 else map + 1
    var old = m.player()
    var hp = word(s, old + HEALTH)
    var armor = word(s, old + ARMOR)
    var bullets = word(s, 5)
    var skill = word(s, old + SKILL)
    var weapons = word(s, old + WEAPONS)
    var equipped = word(s, old + EQUIPPED)
    var shells = word(s, old + SHELLS)
    var rockets = word(s, old + ROCKETS)
    var backpack = word(s, old + BACKPACK)
    var armor_class = word(s, old + ARMOR_CLASS)
    pump_audio(m, voices, 4 if finale else 2, 3584)
    if not external_call["cl_change_map", Int32](Int32(next_map)):
        return -2
    m = current_map()
    m.decode(True)
    if gpu:
        m.upload(True)
    m.spawn(s, skill)
    if not finale:
        s[unsafe_offset=m.player() + HEALTH] = Int32(hp)
        s[unsafe_offset=m.player() + ARMOR] = Int32(armor)
        s[unsafe_offset=m.player() + SKILL] = Int32(skill)
        s[unsafe_offset=5] = Int32(bullets)
        s[unsafe_offset=m.player() + WEAPONS] = Int32(weapons)
        s[unsafe_offset=m.player() + EQUIPPED] = Int32(equipped)
        s[unsafe_offset=m.player() + SHELLS] = Int32(shells)
        s[unsafe_offset=m.player() + ROCKETS] = Int32(rockets)
        s[unsafe_offset=m.player() + BACKPACK] = Int32(backpack)
        s[unsafe_offset=m.player() + ARMOR_CLASS] = Int32(armor_class)
    return -1


def report(m: Hangar, s: I):
    var living = 0
    var awake = 0
    var missiles = 0
    for i in range(word(m.ix, 12)):
        var a = m.actor(i)
        if word(s, a + FLIGHT) > 0:
            missiles += 1
        if word(s, a + MODE) < DEAD and word(s, a + HP) > 0 and word(m.ix, m.sprite(i) + 5) != 2035:
            living += 1
            if word(s, a + MODE) != ASLEEP:
                awake += 1
    _ = external_call["cl_combat_report", Int32](
        Int32(word(s, m.player() + KILLS)),
        Int32(living),
        Int32(awake),
        Int32(word(s, m.player() + HEALTH)),
        Int32(missiles),
    )


def menu_patch(m: Hangar, p: P, id: Int, x: Int, y: Int, center: Bool = False):
    raw_patch(m, p, word(m.ix, word(m.layout, 5) + 2 * id), x, y, center)


def raw_patch(m: Hangar, p: P, patch: Int, x: Int, y: Int, center: Bool = False):
    var width = w(m.wad, patch)
    var left = x - width // 2 if center else x
    for col in range(max(0, -left), min(width, 320 - left)):
        var post = patch + dw(m.wad, patch + 8 + col * 4)
        while rd(m.wad, post) != 255:
            var top = y + rd(m.wad, post)
            var length = rd(m.wad, post + 1)
            for row in range(max(0, -top), min(length, 200 - top)):
                p[unsafe_offset=(top + row) * 320 + left + col] = m.rgba(
                    rd(m.wad, post + 3 + row), 0
                )
            post += length + 4


def score_number(m: Hangar, p: P, value: Int, right: Int, y: Int):
    var n = max(0, value)
    var x = right
    while True:
        x -= 14
        menu_patch(m, p, 28 + n % 10, x, y)
        n = n // 10
        if n == 0:
            break


def intermission(m: Hangar, p: P, s: I, elapsed: Float64):
    var map = Int(external_call["cl_map", Int32]())
    var mission = (map - 1) % 9 + 1
    if mission == 8:
        menu_patch(m, p, 26, 0, 0)
        return
    menu_patch(m, p, 17, 0, 0)
    if Int(elapsed) % 8 >= 5:
        var next_map = 9 if word(s, 6) == 2 else 4 if mission == 9 else mission + 1
        menu_patch(m, p, 19, 160, 8, True)
        menu_patch(m, p, 37 + next_map, 160, 31, True)
        return
    menu_patch(m, p, 37 + mission, 160, 6, True)
    menu_patch(m, p, 18, 160, 24, True)
    var monsters = 0
    var items = 0
    var secrets = 0
    for i in range(word(m.ix, 12)):
        var t = m.sprite(i)
        var mask = (
            1 if word(s, m.player() + SKILL) <= 2 else 2 if word(s, m.player() + SKILL) == 3 else 4
        )
        if not (word(m.ix, t + 7) & mask):
            continue
        var kind = word(m.ix, t + 5)
        if hit_points(kind) > 0 and kind != 2035:
            monsters += 1
        if kind in (2013, 2014, 2015, 2024, 2026, 2045):
            items += 1
    for sec in range(m.sectors()):
        if w(m.wad, m.lump(3) + sec * 26 + 22) == 9:
            secrets += 1
    for row in range(3):
        var y = 55 + row * 24
        menu_patch(m, p, 20 + row, 38, y)
        var total = monsters if row == 0 else items if row == 1 else secrets
        var got = word(s, m.player() + (KILLS if row == 0 else ITEMS if row == 1 else SECRETS))
        score_number(m, p, 100 * got // total if total else 100, 246, y)
        menu_patch(m, p, 24, 248, y)
    menu_patch(m, p, 23, 38, 138)
    var seconds = word(s, 7) // 35
    score_number(m, p, seconds // 60, 214, 138)
    menu_patch(m, p, 25, 215, 138)
    menu_patch(m, p, 28 + (seconds % 60) // 10, 227, 138)
    menu_patch(m, p, 28 + seconds % 10, 241, 138)


def draw_menu(m: Hangar, p: P, page: Int, selection: Int, time: Int):
    menu_patch(m, p, 0, 0, 0)
    for y in range(21 if page in (2, 3) else 85, 185):
        for x in range(34, 286):
            var i = y * 320 + x
            var c = p[unsafe_offset=i]
            p[unsafe_offset=i] = UInt32(0xFF000000) | ((c >> 2) & UInt32(0x3F3F3F))
    if page == 3:
        menu_patch(m, p, 10, 160, 34, True)
        for i in range(5):
            menu_patch(m, p, 11 + i, 68, 62 + 22 * i)
        menu_patch(m, p, 6 + (time // 8) % 2, 42, 62 + 22 * selection)
    elif page == 5:
        menu_patch(m, p, 6 + (time // 8) % 2, 67, 100 + 21 * selection)
    elif page == 2:
        menu_patch(m, p, 8, 160, 39, True)
        menu_patch(m, p, 9, 70, 69)
        menu_patch(m, p, 6 + (time // 8) % 2, 43, 69)
    else:
        var options = 5 if page == 4 else 3
        var y = 82 if page == 4 else 93
        var step = 19 if page == 4 else 20
        for i in range(options):
            var id = 2 if i == 0 else 3 if i == 1 else 4 if i == 2 and page == 4 else 5
            if page != 4 or i != 3:
                menu_patch(m, p, id, 102, y + step * i)
        menu_patch(m, p, 6 + (time // 8) % 2, 74, y + step * selection)


def draw_automap(m: Hangar, p: P, s: I):
    for i in range(320 * 168):
        p[unsafe_offset=i] = 0xFF121013
    var px = Float32(word(s, 0)) / 256
    var py = Float32(word(s, 1)) / 256
    for i in range(m.length(1) // 14):
        var ax, ay, bx, by = m.endpoints(i)
        var l = m.lump(1) + 14 * i
        var flags = w(m.wad, l + 4)
        if flags & 128:
            continue
        var seen = (
            (flags & 256) != 0 or word(s, m.line_state(i)) & 2 or word(s, m.player() + MAP_POWER)
        )
        if not seen:
            continue
        var two = w(m.wad, l + 12) != 65535
        if (
            two
            and not w(m.wad, l + 6)
            and m.height(s, 2 * m.side_sector(w(m.wad, l + 10)))
            == m.height(s, 2 * m.side_sector(w(m.wad, l + 12)))
        ):
            continue
        var x0 = 160 + Int((ax - px) * 0.15)
        var y0 = 84 - Int((ay - py) * 0.15)
        var x1 = 160 + Int((bx - px) * 0.15)
        var y1 = 84 - Int((by - py) * 0.15)
        if max(x0, x1) < 0 or min(x0, x1) >= 320 or max(y0, y1) < 0 or min(y0, y1) >= 168:
            continue
        var n = max(1, max(abs(x1 - x0), abs(y1 - y0)))
        for j in range(n + 1):
            var x = x0 + (x1 - x0) * j // n
            var y = y0 + (y1 - y0) * j // n
            if 0 <= x < 320 and 0 <= y < 168:
                p[unsafe_offset=y * 320 + x] = 0xFFB15445 if not two else 0xFFBE9F66
    var angle = Float32(word(s, 2)) * 0.0015339808
    for j in range(9):
        var x = 160 + Int(Float32(j) * cos(angle))
        var y = 84 - Int(Float32(j) * sin(angle))
        p[unsafe_offset=y * 320 + x] = 0xFFEBEBEB
