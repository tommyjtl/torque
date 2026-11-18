import classic
from std.ffi import external_call
from std.math import abs, atan2, cos, floor, max, min, sin, sqrt
from std.memory import MutPointer
from std.origin import MutUntrackedOrigin

comptime Bytes = MutPointer[UInt8, MutUntrackedOrigin]
comptime Pixels = MutPointer[UInt32, MutUntrackedOrigin]
comptime Floats = MutPointer[Float32, MutUntrackedOrigin]
comptime Words = MutPointer[Int32, MutUntrackedOrigin]
comptime W = 320
comptime H = 200
comptime HUD = 22
comptime VIEW = H - HUD
comptime HORIZON = 85
comptime FX = Float32(160)
comptime FY = Float32(160.0 / 1.2)
comptime EYE = Float32(40)


def byte(p: Bytes, i: Int) -> Int:
    return Int(p[unsafe_offset=i])


def u16(p: Bytes, i: Int) -> Int:
    return byte(p, i) + (byte(p, i + 1) << 8)


def s16(p: Bytes, i: Int) -> Int:
    return Int(Int16(UInt16(u16(p, i))))


def u32(p: Bytes, i: Int) -> Int:
    return u16(p, i) + (u16(p, i + 2) << 16)


def tag(p: Bytes, i: Int) -> UInt64:
    var n = UInt64(0)
    for j in range(8):
        n |= UInt64(byte(p, i + j)) << UInt64(8 * j)
    return n


def lump(p: Bytes, key: UInt64, size: Int, required: Int = -1) -> Int:
    var d = u32(p, 8)
    for i in range(u32(p, 4)):
        var o = d + i * 16
        if tag(p, o + 8) == key:
            var start = u32(p, o)
            var length = u32(p, o + 4)
            if start >= 12 and length <= size - start and (required < 0 or length == required):
                return start
            return -1
    return -1


comptime N_THINGS = UInt64(0x53474E494854)
comptime N_LINEDEFS = UInt64(0x53464544454E494C)
comptime N_VERTEXES = UInt64(0x5345584554524556)
comptime N_SIDEDEFS = UInt64(0x5346454445444953)
comptime N_SECTORS = UInt64(0x53524F54434553)
comptime N_NODES = UInt64(0x5345444F4E)
comptime N_SEGS = UInt64(0x53474553)
comptime N_SSECTORS = UInt64(0x53524F5443455353)
comptime N_PLAYPAL = UInt64(0x4C415059414C50)
comptime N_COLORMAP = UInt64(0x50414D524F4C4F43)
comptime N_SWATLAS = UInt64(0x53414C54415753)
comptime N_SWLABELS = UInt64(0x534C4542414C5753)
comptime N_MAP01 = UInt64(0x313050414D)


@fieldwise_init
struct Map(Copyable, Movable):
    var data: Bytes
    var verts: Int
    var lines: Int
    var sides: Int
    var sectors: Int
    var segs: Int
    var leaves: Int
    var nodes: Int
    var things: Int
    var pal: Int
    var lights: Int
    var atlas: Int
    var labels: Int

    def vertex(self, index: Int, axis: Int) -> Float32:
        return Float32(s16(self.data, self.verts + 4 * index + 2 * axis))

    def sector(self, x: Float32, y: Float32) -> Int:
        var node = 1
        for _ in range(2):
            var p = self.nodes + 28 * node
            var dx = Float32(s16(self.data, p + 4))
            var dy = Float32(s16(self.data, p + 6))
            var side = Int(
                dx * (y - Float32(s16(self.data, p + 2)))
                > dy * (x - Float32(s16(self.data, p)))
            )
            node = u16(self.data, p + 24 + 2 * side)
            if node >= 32768:
                var first = u16(self.data, self.leaves + (node - 32768) * 4 + 2)
                var seg = self.segs + 12 * first
                var l = self.lines + 14 * u16(self.data, seg + 6)
                var s = u16(self.data, l + 10 + 2 * u16(self.data, seg + 8))
                return u16(self.data, self.sides + 30 * s + 28)
        return 0

    def ceiling(self, sector: Int, door: Int) -> Float32:
        var z = Float32(s16(self.data, self.sectors + 26 * sector + 2))
        return Float32(door) if sector == 1 else z

    def pixel(self, mat: Int, u: Int, v: Int, light: Int) -> UInt32:
        var index = byte(self.data, self.atlas + mat * 4096 + ((v & 63) << 6) + (u & 63))
        if index == 0 and mat == 5:
            return 0
        var c = self.pal + 3 * byte(self.data, self.lights + light * 256 + index)
        return UInt32(0xFF000000) | UInt32(
            byte(self.data, c) << 16 | byte(self.data, c + 1) << 8 | byte(self.data, c + 2)
        )

    def light(self, sector: Int) -> Int:
        return min(7, (255 - byte(self.data, self.sectors + 26 * sector + 20)) // 12)


# This first reader admits the fixture's three rectangular sectors and two-node BSP.
# Check every index before traversing a lump or following a cross-reference.
def valid(m: Map) -> Bool:
    if min(m.verts, min(m.lines, min(m.sides, min(m.sectors, min(m.segs, m.leaves))))) < 0:
        return False
    if min(m.nodes, min(m.things, min(m.pal, min(m.lights, min(m.atlas, m.labels))))) < 0:
        return False
    for i in range(12):
        if abs(m.vertex(i, 0)) > 2048 or abs(m.vertex(i, 1)) > 2048:
            return False
    for i in range(14):
        var l = m.lines + 14 * i
        var a = u16(m.data, l)
        var b = u16(m.data, l + 2)
        if a >= 12 or b >= 12 or a == b:
            return False
        var front = u16(m.data, l + 10)
        var back = u16(m.data, l + 12)
        if front >= 16 or (back != 65535 and back >= 16):
            return False
    for i in range(16):
        if u16(m.data, m.sides + 30 * i + 28) >= 3:
            return False
        var seg = m.segs + 12 * i
        var line = u16(m.data, seg + 6)
        var side = u16(m.data, seg + 8)
        if line >= 14 or side > 1:
            return False
        if u16(m.data, m.lines + 14 * line + 10 + 2 * side) >= 16:
            return False
    for i in range(3):
        var n = u16(m.data, m.leaves + i * 4)
        var first = u16(m.data, m.leaves + i * 4 + 2)
        if n == 0 or first + n > 16:
            return False
    for i in range(2):
        for side in range(2):
            var child = u16(m.data, m.nodes + 28 * i + 24 + 2 * side)
            if child >= 32768:
                if child - 32768 >= 3:
                    return False
            elif child >= i:
                return False
    return True


# Save payload, also the authoritative simulation state. Positions are 24.8 fixed
# point, angles have 4096 steps per turn, door height is in map units.
comptime X = 0
comptime Y = 1
comptime ANG = 2
comptime DOOR = 3
comptime OPEN = 4
comptime SIGNAL = 5
comptime WON = 6
comptime TIC = 7
comptime FLASH = 8
comptime MSG = 9  # ephemeral UI state, excluded from saves / hashes
comptime MSGTIME = 10


def val(s: Words, i: Int) -> Int:
    return Int(s[unsafe_offset=i])


def put(s: Words, i: Int, n: Int):
    s[unsafe_offset=i] = Int32(n)


def xval(s: Words, i: Int) -> Float32:
    return Float32(val(s, i)) / 256


def radians(s: Words) -> Float32:
    return Float32(val(s, ANG)) * (6.283185307 / 4096)


def spawn(m: Map, s: Words):
    for i in range(11):
        put(s, i, 0)
    put(s, X, 256 * s16(m.data, m.things))
    put(s, Y, 256 * s16(m.data, m.things + 2))
    put(s, ANG, (s16(m.data, m.things + 4) * 4096 // 360) & 4095)


def endpoints(m: Map, i: Int) -> Tuple[Float32, Float32, Float32, Float32]:
    var a = u16(m.data, m.lines + 14 * i)
    var b = u16(m.data, m.lines + 14 * i + 2)
    return (m.vertex(a, 0), m.vertex(a, 1), m.vertex(b, 0), m.vertex(b, 1))


def blocked(m: Map, s: Words, x: Float32, y: Float32) -> Bool:
    for i in range(14):
        var l = m.lines + 14 * i
        if u16(m.data, l + 12) != 65535 and val(s, DOOR) >= 56:
            continue
        var ax, ay, bx, by = endpoints(m, i)
        var dx = bx - ax
        var dy = by - ay
        var t = min(
            Float32(1),
            max(
                Float32(0),
                ((x - ax) * dx + (y - ay) * dy) / max(Float32(0.001), dx * dx + dy * dy),
            ),
        )
        var ex = x - (ax + t * dx)
        var ey = y - (ay + t * dy)
        if ex * ex + ey * ey < 100:
            return True
    return False


def intersect(
    x: Float32,
    y: Float32,
    rx: Float32,
    ry: Float32,
    ax: Float32,
    ay: Float32,
    bx: Float32,
    by: Float32,
) -> Tuple[Float32, Float32]:
    var ex = bx - ax
    var ey = by - ay
    var d = rx * ey - ry * ex
    if abs(d) < 0.0001:
        return (1e6, 0)
    var t = ((ax - x) * ey - (ay - y) * ex) / d
    var u = ((ax - x) * ry - (ay - y) * rx) / d
    if t < 0.05 or u < 0 or u > 1:
        return (1e6, 0)
    return (t, u)


def usable(m: Map, s: Words) -> Int:
    var closest = Float32(66)
    var action = 0
    var heading = radians(s)
    for i in range(14):
        var ax, ay, bx, by = endpoints(m, i)
        var t, _u = intersect(
            xval(s, X), xval(s, Y), cos(heading), sin(heading), ax, ay, bx, by
        )
        if t < closest:
            closest = t
            action = u16(m.data, m.lines + 14 * i + 6)
    return action


def tick(m: Map, s: Words, forward: Int, strafe: Int, turn: Int, use: Bool, fire: Bool):
    if val(s, WON):
        return
    put(s, TIC, (val(s, TIC) + 1) & 0x3FFFFFFF)
    put(s, ANG, (val(s, ANG) + turn) & 4095)
    put(s, FLASH, max(0, val(s, FLASH) - 1))
    put(s, MSGTIME, max(0, val(s, MSGTIME) - 1))
    var angle = radians(s)
    var c = cos(angle)
    var sn = sin(angle)
    var speed = Float32(2.12) if forward != 0 and strafe != 0 else Float32(3)
    var x = xval(s, X)
    var y = xval(s, Y)
    var nx = x + speed * (Float32(forward) * c + Float32(strafe) * sn)
    var ny = y + speed * (Float32(forward) * sn - Float32(strafe) * c)
    if not blocked(m, s, nx, y):
        put(s, X, Int(nx * 256))
    if not blocked(m, s, xval(s, X), ny):
        put(s, Y, Int(ny * 256))
    if use:
        var action = usable(m, s)
        if action == 1:
            put(s, OPEN, 1)
        if action == 11 and val(s, SIGNAL):
            put(s, WON, 1)
    if val(s, OPEN):
        put(s, DOOR, min(92, val(s, DOOR) + 3))
    if fire:
        put(s, FLASH, 4)
        var dx = Float32(s16(m.data, m.things + 10)) - xval(s, X)
        var dy = Float32(s16(m.data, m.things + 12)) - xval(s, Y)
        var t = dx * c + dy * sn
        if t > 0 and abs(dy * c - dx * sn) < 12:
            var clear = True
            for i in range(14):
                if u16(m.data, m.lines + 14 * i + 12) != 65535 and val(s, DOOR) > 40:
                    continue
                var ax, ay, bx, by = endpoints(m, i)
                var d, _u = intersect(xval(s, X), xval(s, Y), c, sn, ax, ay, bx, by)
                if d < t:
                    clear = False
            if clear:
                put(s, SIGNAL, 1)


def label(m: Map, p: Pixels, id: Int, x: Int, y: Int, color: UInt32):
    for row in range(5):
        for col in range(128):
            if x + col >= W:
                break
            if byte(m.data, m.labels + id * 768 + row * 128 + col):
                p[unsafe_offset=(y + row) * W + x + col] = color


# Same 3x5 glyphs as the fixture labels, indexed by ASCII from space to Z.
comptime KEY_FONT: StaticString = (
    "00000000000000000000000000000000000000000000000000"
    "00000027200000000700000001124475557262276124761216"
    "55711746163465271222252522531600000000000000000000"
    "00000000000000025755656563444365556746477464434553"
    "55755722271115255655444475775557775255526564425573"
    "656553421672222555575555255775552555522271247"
)


def key_hint(p: Pixels, caption: StaticString, x: Int, y: Int):
    var chars = caption.as_bytes()
    var font = KEY_FONT.as_bytes()
    for i in range(len(chars)):
        var glyph = (Int(chars.unsafe_ptr()[unsafe_offset=i]) - 32) * 5
        if glyph < 0 or glyph + 5 > len(font):
            continue
        for row in range(5):
            var bits = Int(font.unsafe_ptr()[unsafe_offset=glyph + row]) - 48
            for col in range(3):
                if bits & (4 >> col):
                    p[unsafe_offset=(y + row) * W + x + 4 * i + col] = 0xFFFFE6B0


def keypad_legend(p: Pixels, expanded: Bool):
    # Keep the exit key legible after startup help closes, in either renderer.
    for y in range(4, 15):
        for x in range(W - 36, W - 4):
            p[unsafe_offset=y * W + x] = 0xFF172423
    key_hint(p, "0 EXIT", W - 32, 7)
    if expanded:
        for y in range(4, 49):
            for x in range(4, 120):
                p[unsafe_offset=y * W + x] = 0xFF172423
        key_hint(p, "8/2 MOVE   4/6 TURN", 8, 8)
        key_hint(p, "7/9 STRAFE   5 FIRE", 8, 16)
        key_hint(p, "ENTER USE   / HELP", 8, 24)
        key_hint(p, "+ SAVE   - LOAD", 8, 32)
        key_hint(p, "0 OR BACKSPACE EXIT", 8, 40)


def hud(m: Map, s: Words, p: Pixels, captured: Bool):
    for y in range(VIEW, H):
        for x in range(W):
            p[unsafe_offset=y * W + x] = 0xFF9BA7A1 if y == VIEW else 0xFF172423
    var accent = UInt32(0xFF71DAC5)
    label(m, p, 0, 7, VIEW + 4, accent)
    label(m, p, 1 if m.sector(xval(s, X), xval(s, Y)) == 0 else 2, 7, VIEW + 13, 0xFFB8C6BB)
    label(m, p, 9, 210, VIEW + 9, 0xFFC4CDC5)
    var action = usable(m, s)
    var id = (14 if val(s, SIGNAL) else 6) if val(s, OPEN) else 3
    if action == 1 and not val(s, OPEN):
        id = 4
    if action == 11:
        id = 5 if val(s, SIGNAL) else 6
    if val(s, WON):
        id = 7
    if val(s, MSGTIME) > 0:
        id = val(s, MSG)
    label(m, p, id, 86, VIEW + 8, 0xFFF8C076)
    if val(s, WON):
        label(m, p, 20, 126, 103, 0xFFFFD49A)
    if not captured:
        label(m, p, 13, 125, 9, 0xFFFFFFFF)
    for i in range(-3, 4):
        if abs(i) > 1:
            p[unsafe_offset=HORIZON * W + W // 2 + i] = 0xFFF8DBA5
            p[unsafe_offset=(HORIZON + i) * W + W // 2] = 0xFFF8DBA5
    # Hand-held signal probe with a sight and an emissive charge indicator.
    for y in range(VIEW - 24, VIEW):
        var width = 3 + (y - (VIEW - 24)) // 2
        for x in range(-width, width + 1):
            var col = UInt32(0xFF293B3C) if x < 0 else UInt32(0xFF425556)
            if abs(x) == width:
                col = 0xFF121C1C
            if abs(x) < 2 and y < VIEW - 14:
                col = 0xFFFFBD72 if val(s, FLASH) else accent
            p[unsafe_offset=y * W + W // 2 + x] = col


def wall(m: Map, s: Words, i: Int) -> Tuple[Int, Float32, Float32, Int]:
    var l = m.lines + 14 * i
    var light = m.light(u16(m.data, m.sides + 30 * u16(m.data, l + 10) + 28))
    if u16(m.data, l + 12) != 65535:
        return (1, Float32(val(s, DOOR)), 96, light)
    return (2 if u16(m.data, l + 6) == 11 else 0, 0, 96, light)


def column(
    m: Map,
    p: Pixels,
    z: Floats,
    x: Int,
    dist: Float32,
    u: Int,
    bottom: Float32,
    top: Float32,
    mat: Int,
    light: Int,
    sprite: Bool,
):
    if dist < 0.1 or dist >= 1e5:
        return
    var y0 = max(0, Int(Float32(HORIZON) - (top - EYE) * FY / dist))
    var y1 = min(VIEW - 1, Int(Float32(HORIZON) - (bottom - EYE) * FY / dist))
    for y in range(y0, y1 + 1):
        var offset = y * W + x
        if dist >= z[unsafe_offset=offset]:
            continue
        var world_z = EYE + (Float32(HORIZON) - Float32(y) - 0.5) * dist / FY
        if world_z < bottom or world_z > top:
            continue
        var v = (top - world_z) * 64 / (top - bottom) if sprite else 96 - world_z
        var color = m.pixel(mat, u, Int(v), light)
        if color != 0:
            p[unsafe_offset=offset] = color
            z[unsafe_offset=offset] = dist


def software(m: Map, s: Words, p: Pixels, z: Floats):
    var x = xval(s, X)
    var y = xval(s, Y)
    var c = cos(radians(s))
    var sn = sin(radians(s))
    # Flat spans. The BSP gives the sector light and material at the sample.
    for row in range(VIEW):
        var den = Float32(HORIZON) - Float32(row) - 0.5
        var dist = (Float32(96) - EYE if den > 0 else -EYE) * FY / den
        var door_dist = (Float32(val(s, DOOR)) - EYE) * FY / den
        var lateral = (0.5 - Float32(W) / 2) / FX
        var wx = x + dist * (c + sn * lateral)
        var wy = y + dist * (sn - c * lateral)
        var sx = dist * sn / FX
        var sy = -dist * c / FX
        for col in range(W):
            var px = wx
            var py = wy
            var depth = dist
            if door_dist > 0 and door_dist < dist and den > 0:
                var side = (Float32(col) + 0.5 - Float32(W) / 2) / FX
                var dx = x + door_dist * (c + sn * side)
                var dy = y + door_dist * (sn - c * side)
                if dx >= 256 and dx <= 288 and dy >= 60 and dy <= 132:
                    px = dx
                    py = dy
                    depth = door_dist
            p[unsafe_offset=row * W + col] = m.pixel(
                4 if den > 0 else 3, Int(floor(px)), Int(floor(py)), m.light(m.sector(px, py))
            )
            z[unsafe_offset=row * W + col] = depth
            wx += sx
            wy += sy
    for i in range(14):
        var ax, ay, bx, by = endpoints(m, i)
        var mat, low, high, light = wall(m, s, i)
        var length = abs(bx - ax) + abs(by - ay)
        for col in range(W):
            var side = (Float32(col) + 0.5 - Float32(W) / 2) / FX
            var d, u = intersect(x, y, c + sn * side, sn - c * side, ax, ay, bx, by)
            column(m, p, z, col, d, Int(u * length), low, high, mat, light, False)
    var dx = Float32(s16(m.data, m.things + 10)) - x
    var dy = Float32(s16(m.data, m.things + 12)) - y
    var d = dx * c + dy * sn
    if d > 0.2:
        var center = Float32(W) / 2 + (dx * sn - dy * c) * FX / d
        var half = 18 * FX / d
        for col in range(max(0, Int(center - half)), min(W, Int(center + half) + 1)):
            var u = (Float32(col) + 0.5 - center + half) * 32 / half
            if u >= 0 and u < 64:
                column(m, p, z, col, d, Int(u), 0, 58, 5, 0 if val(s, SIGNAL) else 4, True)


def quad(
    mat: Int,
    light: Int,
    ax: Float32,
    ay: Float32,
    bx: Float32,
    by: Float32,
    low: Float32,
    high: Float32,
    ustep: Float32,
):
    _ = external_call["sw_wall", Int32](
        Int32(mat), Int32(light), ax, ay, bx, by, low, high, ustep
    )


def hardware(m: Map, s: Words):
    _ = external_call["sw_camera", Int32](xval(s, X), xval(s, Y), radians(s))
    # Derive the axis-aligned fixture sector bounds from its BSP subsector segments.
    for sector in range(3):
        var first = u16(m.data, m.leaves + sector * 4 + 2)
        var count = u16(m.data, m.leaves + sector * 4)
        var xmin = Float32(1e5)
        var xmax = Float32(-1e5)
        var ymin = xmin
        var ymax = xmax
        for j in range(first, first + count):
            var vertex = u16(m.data, m.segs + 12 * j)
            var x = m.vertex(vertex, 0)
            var y = m.vertex(vertex, 1)
            xmin = min(xmin, x)
            xmax = max(xmax, x)
            ymin = min(ymin, y)
            ymax = max(ymax, y)
        _ = external_call["sw_flat", Int32](
            Int32(3), Int32(m.light(sector)), xmin, ymin, xmax, ymax, Float32(0)
        )
        _ = external_call["sw_flat", Int32](
            Int32(4),
            Int32(m.light(sector)),
            xmin,
            ymin,
            xmax,
            ymax,
            m.ceiling(sector, val(s, DOOR)),
        )
    for i in range(14):
        var ax, ay, bx, by = endpoints(m, i)
        var mat, low, high, light = wall(m, s, i)
        quad(mat, light, ax, ay, bx, by, low, high, abs(bx - ax) + abs(by - ay))
    var x = Float32(s16(m.data, m.things + 10))
    var y = Float32(s16(m.data, m.things + 12))
    var rx = sin(radians(s)) * 18
    var ry = -cos(radians(s)) * 18
    quad(5, 0 if val(s, SIGNAL) else 4, x - rx, y - ry, x + rx, y + ry, 0, 58, 64)


def load_state(m: Map, s: Words, tmp: Words) -> Bool:
    if external_call["sw_load", Int32](tmp) == 0:
        return False
    var door = val(tmp, DOOR)
    if door < 0 or door > 92 or val(tmp, ANG) < 0 or val(tmp, ANG) > 4095:
        return False
    for field in range(OPEN, WON + 1):
        if val(tmp, field) != 0 and val(tmp, field) != 1:
            return False
    if val(tmp, FLASH) < 0 or val(tmp, FLASH) > 4 or val(tmp, TIC) < 0:
        return False
    var x = xval(tmp, X)
    var y = xval(tmp, Y)
    if (
        x < 10
        or x > 534
        or y < 10
        or y > 182
        or (x >= 256 and x <= 288 and (y < 70 or y > 122))
    ):
        return False
    if blocked(m, tmp, x, y):
        return False
    for i in range(9):
        put(s, i, val(tmp, i))
    return True


# C entry runs this function once; Mojo owns map parsing, the event/tick loop and both draw paths.
@export("switchyard_run")
def switchyard_run(
    p: Bytes,
    size32: Int32,
    pixels: Pixels,
    depth: Floats,
    state: Words,
    tmp: Words,
    mode: Int32,
    config: Int32,
    limit: Int32,
) abi("C") -> Int32:
    var size = Int(size32)
    if size < 12 or u32(p, 0) != 0x44415750 or u32(p, 4) > 128:
        return 2
    if u32(p, 8) < 12 or u32(p, 8) > size - 16 * u32(p, 4):
        return 2
    if lump(p, N_MAP01, size, 0) < 0:
        return 2
    var m = Map(
        p,
        lump(p, N_VERTEXES, size, 48),
        lump(p, N_LINEDEFS, size, 196),
        lump(p, N_SIDEDEFS, size, 480),
        lump(p, N_SECTORS, size, 78),
        lump(p, N_SEGS, size, 192),
        lump(p, N_SSECTORS, size, 12),
        lump(p, N_NODES, size, 56),
        lump(p, N_THINGS, size, 20),
        lump(p, N_PLAYPAL, size, 768),
        lump(p, N_COLORMAP, size, 8192),
        lump(p, N_SWATLAS, size, 24576),
        lump(p, N_SWLABELS, size, 21 * 768),
    )
    if not valid(m):
        return 2
    var flags = Int(config)
    var original = (flags & 16) != 0
    var hangar = classic.Hangar(
        external_call["cl_wad", Bytes](),
        external_call["cl_ix", Words](),
        external_call["cl_ix", Floats](),
        external_call["cl_texels", Pixels](),
        external_call["cl_bases", Words](),
    )
    var voices = external_call["cl_voices", Words]()
    if original:
        hangar.decode()
        hangar.spawn(state)
    else:
        spawn(m, state)
    if flags & 2 and not (
        classic.restore(hangar, state, tmp) if original else load_state(m, state, tmp)
    ):
        return 3
    # Offline deterministic acceptance: first try walking through the closed door,
    # then use it, wait for clearance, cross, use the exit, restore the closed save.
    if original and flags & 4:
        classic.compose(hangar, state, pixels, depth, False)
        classic.overlay(hangar, pixels, state)
        _ = external_call["sw_report", Int32](state, pixels, Int32(0), Int32(0))
        return 0
    if flags & 4:
        for _ in range(80):
            tick(m, state, 1, 0, 0, False, False)
        if xval(state, X) > 246 or val(state, DOOR) != 0:
            return 10
        if external_call["sw_save", Int32](state) == 0:
            return 11
        for i in range(150):
            tick(m, state, 1, 0, 0, i == 0 or i == 149, i == 52)
        if val(state, WON) != 1:
            return 12
        if not load_state(m, state, tmp) or val(state, DOOR) != 0 or val(state, WON) != 0:
            return 13
        software(m, state, pixels, depth)
        hud(m, state, pixels, True)
        _ = external_call["sw_report", Int32](state, pixels, Int32(0), Int32(0))
        return 0
    if external_call["sw_open", Int32](mode) == 0:
        return 4
    if mode == 1 and original:
        hangar.upload()
    if mode == 1 and not original:
        for mat in range(6):
            for light in range(8):
                for i in range(4096):
                    pixels[unsafe_offset=i] = m.pixel(mat, i & 63, i >> 6, light)
                _ = external_call["sw_texture", Int32](Int32(mat), Int32(light), pixels)
    var held = SIMD[DType.uint64, 2](0)
    var turn = 0
    var help_open = False
    var use = False
    var fire = False
    var captured = external_call["sw_capture", Int32](Int32(1)) != 0
    var last = external_call["sw_clock", Float64]()
    var started = last
    var accumulator = Float64(0)
    var frames = 0
    var ticks = 0
    while True:
        var event = external_call["sw_event", Int32]()
        var quit = False
        while event != 0:
            var e = Int(event)
            if e == 1:
                quit = True
            elif e == 2:
                held = 0
                turn = 0
                use = False
                fire = False
                _ = external_call["sw_capture", Int32](Int32(0))
                captured = False
            elif e == 3:
                if captured:
                    fire = True
                else:
                    captured = external_call["sw_capture", Int32](Int32(1)) != 0
            elif e == 4:
                if captured:
                    turn -= Int(external_call["sw_mouse_dx", Int32]()) * 3
            elif e >= 1000:
                var down = e < 2000
                var key = e % 1000
                # USB scancodes incl. K0 numeric layer. Map actions here, not in SDL.
                # Zero can arrive as keypad 0, number-row 0, or Insert.
                if down and key in (98, 39, 73, 42, 187, 41):
                    quit = True
                if down and key in (43, 84):
                    help_open = not help_open
                if down and (key == 44 or key == 40 or key == 88):
                    if val(state, WON) and not (flags & 1):
                        if original:
                            hangar.spawn(state)
                        else:
                            spawn(m, state)
                    else:
                        use = True
                if down and key in (62, 87):
                    put(state, MSG, 10 if external_call["sw_save", Int32](state) != 0 else 12)
                    put(state, MSGTIME, 45)
                if down and key in (66, 86):
                    var restored = classic.restore(
                        hangar, state, tmp
                    ) if original else load_state(m, state, tmp)
                    put(state, MSG, 11 if restored else 12)
                    put(state, MSGTIME, 45)
                # Center key fires; retain keypad 1 as a second fire button.
                if down and key in (93, 34, 156, 89, 30, 77):
                    fire = True
                if key in (
                    26,
                    82,
                    96,
                    37,
                    22,
                    81,
                    90,
                    31,
                    4,
                    95,
                    74,
                    36,
                    7,
                    97,
                    75,
                    38,
                    80,
                    92,
                    33,
                    79,
                    94,
                    35,
                ):
                    var slot = UInt64(key % 64)
                    if down:
                        held[key // 64] |= UInt64(1) << slot
                    else:
                        held[key // 64] &= ~(UInt64(1) << slot)
            event = external_call["sw_event", Int32]()
        if quit:
            break
        var now = external_call["sw_clock", Float64]()
        if limit > 0 and now - started >= Float64(limit):
            break
        accumulator += min(Float64(0.25), now - last)
        last = now
        while accumulator >= 1.0 / 35.0:
            if (flags & 1) and val(state, TIC) >= 211:
                accumulator = 0
                break

            def pressed(k: Int) {held} -> Bool:
                return (held[k // 64] & (UInt64(1) << UInt64(k % 64))) != 0

            var f = Int(pressed(26) or pressed(82) or pressed(96) or pressed(37)) - Int(
                pressed(22) or pressed(81) or pressed(90) or pressed(31)
            )
            var strafe = Int(pressed(7) or pressed(97) or pressed(75) or pressed(38)) - Int(
                pressed(4) or pressed(95) or pressed(74) or pressed(36)
            )
            var rotation = turn + 38 * (
                Int(pressed(80) or pressed(92) or pressed(33))
                - Int(pressed(79) or pressed(94) or pressed(35))
            )
            if flags & 1:
                f = 1
                strafe = 0
                rotation = 0
                var trace_tick = val(state, TIC)
                use = trace_tick == 70 or trace_tick == 210
                fire = trace_tick == 120
            if flags & 8 and val(state, TIC) == 110:
                if external_call["sw_save", Int32](state) == 0:
                    return 11
            var prior = val(state, OPEN) + val(state, WON)
            if original:
                var effect = hangar.tick(state, f, strafe, rotation, use, fire)
                if effect >= 0:
                    classic.start_sound(hangar, voices, effect)
            else:
                tick(m, state, f, strafe, rotation, use, fire)
            if not original and (fire or prior != val(state, OPEN) + val(state, WON)):
                var pcm = external_call["sw_audio_buffer", Floats]()
                var hz = Float32(170 if fire else 540)
                for sample in range(2205):
                    var phase = Float32(sample) / 2205
                    pcm[unsafe_offset=sample] = (
                        sin(phase * hz * 0.6283185)
                        * (1 - phase)
                        * min(Float32(1), phase * 40)
                        * 0.08
                    )
                _ = external_call["sw_audio", Int32](Int32(2205))
            turn = 0
            use = False
            fire = False
            ticks += 1
            accumulator -= 1.0 / 35.0
        if original:
            classic.pump_audio(hangar, voices)
            classic.compose(hangar, state, pixels, depth, mode == 1)
            classic.overlay(hangar, pixels, state)
            if val(state, WON):
                label(m, pixels, 7, 135, 86, 0xFFFFD49A)
            if val(state, MSGTIME):
                label(m, pixels, val(state, MSG), 8, 48, 0xFFFFD49A)
        elif mode == 0:
            software(m, state, pixels, depth)
        else:
            hardware(m, state)
            for i in range(W * H):
                pixels[unsafe_offset=i] = 0
        if not original:
            hud(m, state, pixels, captured or (flags & 1) != 0)
        keypad_legend(pixels, help_open or val(state, TIC) < 110)
        _ = external_call["sw_present", Int32](pixels, mode)
        frames += 1
    _ = external_call["sw_report", Int32](state, pixels, Int32(frames), Int32(ticks))
    return 0
