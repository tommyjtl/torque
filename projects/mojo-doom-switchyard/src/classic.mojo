"""Hangar exploration milestone using the original shareware 1.9 IWAD."""
from std.ffi import external_call
from std.math import abs, cos, floor, max, min, sin, sqrt
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


@fieldwise_init
struct Hangar(Copyable, Movable):
    var wad: B
    var ix: I
    var f: F
    var tex: P
    var bases: I

    def lump(self, k: Int) -> Int:
        return word(self.ix, 13 + 2 * k)

    def length(self, k: Int) -> Int:
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

    def decode(self):
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
                        self.tex[unsafe_offset=stride + light * area + k] = self.rgba(
                            idx, light
                        )
            stride += 4 * area

    def upload(self):
        for mat in range(word(self.ix, 9)):
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
        return h + word(s, 11 + sector) if k & 1 else h

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

    def spawn(self, s: I):
        for k in range(96):
            s[unsafe_offset=k] = 0
        s[unsafe_offset=5] = 50
        for i in range(self.length(7) // 10):
            var t = self.lump(7) + i * 10
            if w(self.wad, t + 6) == 1:
                s[unsafe_offset=0] = Int32(signed(self.wad, t) * 256)
                s[unsafe_offset=1] = Int32(signed(self.wad, t + 2) * 256)
                s[unsafe_offset=2] = Int32((w(self.wad, t + 4) * 4096 // 360) & 4095)
                return

    def can_move(self, s: I, x: Float32, y: Float32, oldfloor: Int) -> Bool:
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
            if (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2 < 100:
                return False
        return True

    def tick(self, s: I, forward: Int, strafe: Int, turn: Int, use: Bool, fire: Bool) -> Int:
        if word(s, 6):
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
        var oldfloor = self.height(s, self.sector(x, y) * 2)
        if nx != x and self.can_move(s, nx, y, oldfloor):
            s[unsafe_offset=0] = Int32(nx * 256)
        if ny != y and self.can_move(s, Float32(word(s, 0)) / 256, ny, oldfloor):
            s[unsafe_offset=1] = Int32(ny * 256)
        var sound = -1
        if fire and word(s, 5) > 0:
            s[unsafe_offset=5] -= 1
            sound = 10
            s[unsafe_offset=8] = 6
        if use:
            var nearest = Float32(66)
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
                var special = w(self.wad, hit + 6)
                if special == 1 and w(self.wad, hit + 12) != 65535:
                    var sector = self.side_sector(w(self.wad, hit + 12))
                    if word(s, 11 + sector) == 0:
                        s[unsafe_offset=11 + sector] = 1
                        sound = 11
                if special == 11:
                    s[unsafe_offset=6] = 1
                    sound = 12
        for sec in range(85):
            var lift = word(s, 11 + sec)
            if lift > 0:
                # Prepared per-sector upper stop: lowest neighboring ceiling minus four.
                var stop = word(
                    self.ix,
                    word(self.ix, 12) * 5
                    + 46
                    + 5 * word(self.ix, 9)
                    + 4 * word(self.ix, 10)
                    + 17 * word(self.ix, 11)
                    + sec,
                )
                s[unsafe_offset=11 + sec] = Int32(min(stop, lift + 2))
        return sound


def screen(p: V) -> V:
    var iz = 1 / p[2]
    return V(
        160 + 160 * p[0] * iz, 85 - 133.33333 * p[1] * iz, iz, p[3] * iz, p[4] * iz, 0, 0, 0
    )


def side(a: V, b: V, x: Float32, y: Float32) -> Float32:
    return (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])


def raster(a0: V, b0: V, c0: V, tex: P, tw: Int, th: Int, pixels: P, depth: F):
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
                    var color = tex[
                        unsafe_offset=((v % th + th) % th) * tw + (u % tw + tw) % tw
                    ]
                    if color:
                        pixels[unsafe_offset=offset] = color
                        depth[unsafe_offset=offset] = z / area
            e0 += d0
            e1 += d1
            e2 += d2


def cross_near(a: V, b: V) -> V:
    return a + (b - a) * ((1 - a[2]) / (b[2] - a[2]))


def clipped(a: V, b: V, c: V, tex: P, wid: Int, ht: Int, p: P, z: F):
    if a[2] < 1:
        if b[2] < 1:
            if c[2] >= 1:
                raster(c, cross_near(c, a), cross_near(c, b), tex, wid, ht, p, z)
        elif c[2] < 1:
            raster(b, cross_near(b, c), cross_near(b, a), tex, wid, ht, p, z)
        else:
            var ba = cross_near(b, a)
            var ca = cross_near(c, a)
            raster(b, c, ca, tex, wid, ht, p, z)
            raster(b, ca, ba, tex, wid, ht, p, z)
    elif b[2] < 1:
        if c[2] < 1:
            raster(a, cross_near(a, b), cross_near(a, c), tex, wid, ht, p, z)
        else:
            var ab = cross_near(a, b)
            var cb = cross_near(c, b)
            raster(a, ab, cb, tex, wid, ht, p, z)
            raster(a, cb, c, tex, wid, ht, p, z)
    elif c[2] < 1:
        var ac = cross_near(a, c)
        var bc = cross_near(b, c)
        raster(a, b, bc, tex, wid, ht, p, z)
        raster(a, bc, ac, tex, wid, ht, p, z)
    else:
        raster(a, b, c, tex, wid, ht, p, z)


def camera(v: V, eye: V) -> V:
    var dx = v[0] - eye[0]
    var dy = v[1] - eye[1]
    return point(
        dx * eye[4] - dy * eye[3], v[2] - eye[2], dx * eye[3] + dy * eye[4], v[3], v[4]
    )


def submit(m: Hangar, eye: V, a: V, b: V, c: V, mat: Int, light: Int, p: P, z: F, gpu: Bool):
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
            id, a[0], a[1], a[2] - eye[2] + 40, a[3] / Float32(tw), a[4] / Float32(th)
        )
        _ = external_call["cl_vertex", Int32](
            id, b[0], b[1], b[2] - eye[2] + 40, b[3] / Float32(tw), b[4] / Float32(th)
        )
        _ = external_call["cl_vertex", Int32](
            id, c[0], c[1], c[2] - eye[2] + 40, c[3] / Float32(tw), c[4] / Float32(th)
        )
    else:
        clipped(ca, cb, cc, m.tex.unsafe_offset(m.source(mat, light)), tw, th, p, z)


def compose(m: Hangar, s: I, p: P, z: F, gpu: Bool):
    var px = Float32(word(s, 0)) / 256
    var py = Float32(word(s, 1)) / 256
    var angle = Float32(word(s, 2)) * 0.0015339808
    var ca = cos(angle)
    var sn = sin(angle)
    var eye = point(px, py, Float32(m.height(s, m.sector(px, py) * 2) + 40), ca, sn)
    if gpu:
        _ = external_call["sw_camera", Int32](px, py, angle)
    for i in range(320 * 200):
        p[unsafe_offset=i] = 0 if gpu else UInt32(0xFF181820)
        z[unsafe_offset=i] = 0
    var start = 46 + 5 * word(m.ix, 9) + 4 * word(m.ix, 10)
    for t in range(word(m.ix, 11)):
        var k = start + 17 * t
        var mat = word(m.ix, k)
        var sec = word(m.ix, k + 1)
        var light = min(3, max(0, (255 - rd(m.wad, m.lump(3) + sec * 26 + 20)) // 48))
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

        def vertex(i: Int) {m, s, k, vertical} -> V:
            var j = k + 2 + i * 5
            var h = Float32(m.height(s, word(m.ix, j + 2)))
            var v = m.f[unsafe_offset=j + 4]
            if vertical:
                var encoded = Int(v)
                v = Float32(m.height(s, (encoded // 8192) - 1) + (encoded % 8192) - 4096) - h
            return point(
                m.f[unsafe_offset=j], m.f[unsafe_offset=j + 1], h, m.f[unsafe_offset=j + 3], v
            )

        submit(m, eye, vertex(0), vertex(1), vertex(2), mat, light, p, z, gpu)
    start += 17 * word(m.ix, 11)
    for i in range(word(m.ix, 12)):
        var k = start + 5 * i
        var x = Float32(word(m.ix, k))
        var y = Float32(word(m.ix, k + 1))
        var mat = word(m.ix, k + 2)
        var width = m.desc(mat, 0)
        var height = m.desc(mat, 1)
        var left = Float32(word(m.ix, k + 3))
        var sec = m.sector(x, y)
        var hi = Float32(m.height(s, sec * 2) + word(m.ix, k + 4))
        var lo = hi - Float32(height)
        var x0 = x - sn * left
        var y0 = y + ca * left
        var x1 = x0 + sn * Float32(width)
        var y1 = y0 - ca * Float32(width)
        var a = point(x0, y0, lo, 0, Float32(height))
        var b = point(x1, y1, lo, Float32(width), Float32(height))
        var c = point(x1, y1, hi, Float32(width), 0)
        var d = point(x0, y0, hi, 0, 0)
        var light = min(3, (255 - rd(m.wad, m.lump(3) + 26 * sec + 20)) // 48)
        submit(m, eye, a, b, c, mat, light, p, z, gpu)
        submit(m, eye, a, c, d, mat, light, p, z, gpu)
    if gpu:
        _ = external_call["cl_flush", Int32]()


def blit(m: Hangar, p: P, mat: Int, x: Int, y: Int):
    var tw = m.desc(mat, 0)
    var th = m.desc(mat, 1)
    var base = m.source(mat, 0)
    for row in range(max(0, -y), min(th, 200 - y)):
        for col in range(max(0, -x), min(tw, 320 - x)):
            var color = m.tex[unsafe_offset=base + row * tw + col]
            if color:
                p[unsafe_offset=(y + row) * 320 + x + col] = color


def overlay(m: Hangar, p: P, s: I):
    var firing = word(s, 8) > 2
    var gun = word(m.ix, 42 if firing else 41)
    var width = m.desc(gun, 0)
    blit(m, p, gun, 160 - width // 2, 168 - m.desc(gun, 1))
    if firing:
        var flash = word(m.ix, 43)
        blit(
            m,
            p,
            flash,
            160 - m.desc(flash, 0) // 2,
            168 - m.desc(gun, 1) - m.desc(flash, 1) + 4,
        )
    blit(m, p, word(m.ix, 44), 0, 168)
    blit(m, p, word(m.ix, 45), 144, 169)
    var table = (
        46
        + 5 * word(m.ix, 9)
        + 4 * word(m.ix, 10)
        + 17 * word(m.ix, 11)
        + 5 * word(m.ix, 12)
        + 85
    )

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

    number(word(s, 5), 44, 171, False)
    number(100, 90, 171, False)
    number(0, 220, 171, False)
    blit(m, p, word(m.ix, table + 10), 90, 171)
    blit(m, p, word(m.ix, table + 10), 220, 171)
    for i in range(4):
        number(word(s, 5) if i == 0 else 0, 288, 173 + 6 * i, True)
        number(200 if i == 0 else 50 if i == 1 or i == 3 else 300, 314, 173 + 6 * i, True)


# Four independent DMX voices. Store offset, length, source rate and output cursor.
def start_sound(m: Hangar, voices: I, sound: Int):
    var o = m.lump(sound)
    var length = dw(m.wad, o + 4) - 32
    var rate = w(m.wad, o + 2)
    if w(m.wad, o) != 3 or length <= 0 or length + 40 > m.length(sound) or rate <= 0:
        return
    var slot = word(voices, 16) % 4
    voices[unsafe_offset=16] = Int32((slot + 1) % 4)
    voices[unsafe_offset=4 * slot] = Int32(o + 24)
    voices[unsafe_offset=4 * slot + 1] = Int32(length)
    voices[unsafe_offset=4 * slot + 2] = Int32(rate)
    voices[unsafe_offset=4 * slot + 3] = 0
    _ = external_call["cl_sound_event", Int32](Int32(sound))


def pump_audio(m: Hangar, voices: I):
    var pcm = external_call["sw_audio_buffer", F]()
    for _ in range(4):
        if external_call["cl_need_audio", Int32]() == 0:
            return
        var active = False
        for sample in range(512):
            pcm[unsafe_offset=sample] = 0
        for slot in range(4):
            var k = 4 * slot
            var length = word(voices, k + 1)
            if length == 0:
                continue
            var cursor = word(voices, k + 3)
            var rate = word(voices, k + 2)
            var start = word(voices, k)
            active = True
            for sample in range(512):
                var index = (cursor + sample) * rate // 22050
                if index >= length:
                    voices[unsafe_offset=k + 1] = 0
                    break
                pcm[unsafe_offset=sample] += (Float32(rd(m.wad, start + index)) - 128) * (
                    0.23 / 128
                )
            voices[unsafe_offset=k + 3] = Int32(cursor + 512)
        if not active:
            return
        _ = external_call["sw_audio", Int32](Int32(512))


def restore(m: Hangar, state: I, tmp: I) -> Bool:
    if external_call["sw_load", Int32](tmp) == 0:
        return False
    if abs(Float32(word(tmp, 0)) / 256) > 4000 or abs(Float32(word(tmp, 1)) / 256) > 6000:
        return False
    if (
        word(tmp, 2) < 0
        or word(tmp, 2) > 4095
        or word(tmp, 7) < 0
        or word(tmp, 8) < 0
        or word(tmp, 8) > 6
    ):
        return False
    if word(tmp, 5) < 0 or word(tmp, 5) > 50:
        return False
    if word(tmp, 6) != 0 and word(tmp, 6) != 1:
        return False
    var end = (
        46 + 5 * word(m.ix, 9) + 4 * word(m.ix, 10) + 17 * word(m.ix, 11) + 5 * word(m.ix, 12)
    )
    for sec in range(85):
        if word(tmp, 11 + sec) < 0 or word(tmp, 11 + sec) > word(m.ix, end + sec):
            return False
    for k in range(96):
        state[unsafe_offset=k] = tmp[unsafe_offset=k]
    state[unsafe_offset=9] = 0
    state[unsafe_offset=10] = 0
    return True
