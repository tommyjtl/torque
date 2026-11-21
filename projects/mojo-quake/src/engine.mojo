"""Native Mojo engine kernels. SPDX-License-Identifier: GPL-2.0-or-later."""
from qc import Bytes, Floats, Words, Shorts
from std.ffi import external_call
from std.math import min, max
from std.memory import MutPointer
from std.origin import MutUntrackedOrigin

comptime Samples = MutPointer[Int16, MutUntrackedOrigin]


@export("mq_draw_span")
def draw_span(
    dest: Bytes,
    texture: Bytes,
    width: Int32,
    count: Int32,
    s_over_z: Float32,
    t_over_z: Float32,
    inv_z: Float32,
    ds: Float32,
    dt: Float32,
    dz: Float32,
    s_bias: Int32,
    t_bias: Int32,
    s_limit: Int32,
    t_limit: Int32,
) abi("C"):
    # The surface cache already contains mipmapped, lightmapped palette entries.
    # Interpolate in screen space and recover texture coordinates per pixel.
    for i in range(Int(count)):
        var column = Float32(i)
        var reciprocal = inv_z + column * dz
        if reciprocal > 0:
            var scale = Float32(65536) / reciprocal
            var s = (
                min(Int(s_limit), max(0, Int((s_over_z + column * ds) * scale) + Int(s_bias))) >> 16
            )
            var t = (
                min(Int(t_limit), max(0, Int((t_over_z + column * dt) * scale) + Int(t_bias))) >> 16
            )
            dest[unsafe_offset=i] = texture[unsafe_offset=t * Int(width) + s]


def attenuate(value: Int32, gain: Int32) -> Int32:
    var product = Int(value) * Int(gain)
    return Int32((product + (255 if product < 0 else 0)) >> 8)


@export("mq_mix8")
def mix8(
    dst: Words, src: Bytes, left: Words, right: Words, ramp: Bytes, count: Int32, remaining: Int32
) abi("C"):
    var fading = remaining > 0
    for i in range(Int(min(count, remaining) if fading else count)):
        var value = Int(src[unsafe_offset=i])
        var l = left[unsafe_offset=value]
        var r = right[unsafe_offset=value]
        if fading:
            var gain = Int32(ramp[unsafe_offset=Int(remaining) - i])
            l = attenuate(l, gain)
            r = attenuate(r, gain)
        dst[unsafe_offset=2 * i] += l
        dst[unsafe_offset=2 * i + 1] += r


@export("mq_mix16")
def mix16(
    dst: Words, src: Samples, left: Int32, right: Int32, ramp: Bytes, count: Int32, remaining: Int32
) abi("C"):
    var fading = remaining > 0
    for i in range(Int(min(count, remaining) if fading else count)):
        var value = Int32(src[unsafe_offset=i])
        var l = value * left
        var r = value * right
        if fading:
            var gain = Int32(ramp[unsafe_offset=Int(remaining) - i])
            l = attenuate(l, gain)
            r = attenuate(r, gain)
        dst[unsafe_offset=2 * i] += l
        dst[unsafe_offset=2 * i + 1] += r


@export("mq_contents")
def contents(
    nodes: Words,
    planes: Floats,
    plane_bytes: Bytes,
    first: Int32,
    last: Int32,
    start: Int32,
    x: Float32,
    y: Float32,
    z: Float32,
) abi("C") -> Int32:
    var n = Int(start)
    while n >= 0:
        if n < Int(first) or n > Int(last):
            return -99999
        var plane = Int(nodes[unsafe_offset=n * 3])
        var k = plane * 5
        var axis = Int(plane_bytes[unsafe_offset=plane * 20 + 16])
        var projection = x if axis == 0 else y if axis == 1 else z
        if axis >= 3:
            projection = (
                x * planes[unsafe_offset=k]
                + y * planes[unsafe_offset=k + 1]
                + z * planes[unsafe_offset=k + 2]
            )
        var side = Int(projection < planes[unsafe_offset=k + 3])
        n = Int(nodes[unsafe_offset=n * 3 + 1 + side])
    return Int32(n)


@export("mq_clock_loop")
def clock_loop() abi("C"):
    var step = 1.0 / 72.0
    var frame = 1.0 / 60.0
    var next_tick = external_call["mq_now", Float64]()
    var next_frame = next_tick + frame
    # Submit graphics ahead of the presentation deadline. Sudden changes in scene
    # cost should use the frame's spare time before they change its visible cadence.
    var lead = 0.010
    while True:
        var now = external_call["mq_now", Float64]()
        if now - next_tick > 3.0:
            external_call["mq_suspend_gap", NoneType](now - next_tick)
            next_tick = now
            next_frame = now + frame
        while now >= next_tick:
            external_call["mq_tick", NoneType](Float32(step), Int32(0))
            next_tick += step
        now = external_call["mq_now", Float64]()
        if now >= next_frame - lead:
            external_call["mq_draw_to", NoneType](next_frame)
            next_frame += frame
            now = external_call["mq_now", Float64]()
            while next_frame < now:
                next_frame += frame
        var delay = min(next_tick, next_frame - lead) - now
        if delay > 0:
            external_call["mq_wait", NoneType](Int32(min(Float64(2000), delay * 1000000)))


comptime V3 = SIMD[DType.float32, 4]


@fieldwise_init
struct Hull(Copyable, Movable):
    var nodes: Words
    var planes: Floats
    var bytes: Bytes
    var first: Int
    var last: Int

    def leaf(self, n: Int, p: V3) -> Int:
        return Int(
            contents(
                self.nodes,
                self.planes,
                self.bytes,
                Int32(self.first),
                Int32(self.last),
                Int32(n),
                p[0],
                p[1],
                p[2],
            )
        )

    def distance(self, k: Int, p: V3) -> Float32:
        var axis = Int(self.bytes[unsafe_offset=20 * k + 16])
        var proj = p[axis] if axis < 3 else (
            p[0] * self.planes[unsafe_offset=k * 5]
            + p[1] * self.planes[unsafe_offset=k * 5 + 1]
            + p[2] * self.planes[unsafe_offset=k * 5 + 2]
        )
        return proj - self.planes[unsafe_offset=k * 5 + 3]

    def sweep(
        self,
        n: Int,
        low: Float32,
        high: Float32,
        a: V3,
        b: V3,
        flags: Words,
        hit: Floats,
        depth: Int,
    ) -> Int:
        if n < 0:
            if n == -2:
                flags[unsafe_offset=1] = 1
            else:
                flags[unsafe_offset=0] = 0
                flags[unsafe_offset=2 if n == -1 else 3] = 1
            return 1
        if n < self.first or n > self.last or depth > 256:
            return -1
        var plane = Int(self.nodes[unsafe_offset=n * 3])
        var da = self.distance(plane, a)
        var db = self.distance(plane, b)
        var side = Int(da < 0)
        var near = Int(self.nodes[unsafe_offset=n * 3 + 1 + side])
        if side == Int(db < 0):
            return self.sweep(near, low, high, a, b, flags, hit, depth + 1)
        var far = Int(self.nodes[unsafe_offset=n * 3 + 2 - side])
        var epsilon = Float32(0.03125) if side else Float32(-0.03125)
        var split = min(Float32(1), max(Float32(0), (da + epsilon) / (da - db)))
        var mid = a + (b - a) * split
        var time = low + (high - low) * split
        var traversed = self.sweep(near, low, time, a, mid, flags, hit, depth + 1)
        if traversed != 1:
            return traversed
        var beyond = self.leaf(far, mid)
        if beyond == -99999:
            return -1
        if beyond != -2:
            return self.sweep(far, time, high, mid, b, flags, hit, depth + 1)
        if flags[unsafe_offset=0]:
            return 0
        var sign = Float32(-1) if side else Float32(1)
        for j in range(4):
            hit[unsafe_offset=4 + j] = sign * self.planes[unsafe_offset=5 * plane + j]
        while self.leaf(self.first, mid) == -2:
            split -= 0.1
            if split < 0:
                break
            mid = a + (b - a) * split
            time = low + (high - low) * split
        hit[unsafe_offset=0] = time
        for j in range(3):
            hit[unsafe_offset=j + 1] = mid[j]
        return 0


@export("mq_sweep")
def sweep(
    nodes: Words,
    planes: Floats,
    plane_bytes: Bytes,
    first: Int32,
    last: Int32,
    start: Int32,
    a: Floats,
    b: Floats,
    flags: Words,
    hit: Floats,
) abi("C") -> Int32:
    var hull = Hull(nodes, planes, plane_bytes, Int(first), Int(last))
    var p = V3(a[unsafe_offset=0], a[unsafe_offset=1], a[unsafe_offset=2], 0)
    var q = V3(b[unsafe_offset=0], b[unsafe_offset=1], b[unsafe_offset=2], 0)
    return Int32(hull.sweep(Int(start), 0, 1, p, q, flags, hit, 0))


@export("mq_accelerate")
def accelerate(
    velocity: Floats,
    direction: Floats,
    limit: Float32,
    intended: Float32,
    acceleration: Float32,
    delta: Float32,
) abi("C"):
    var current = Float32(0)
    for j in range(3):
        current += velocity[unsafe_offset=j] * direction[unsafe_offset=j]
    var change = min(limit - current, acceleration * intended * delta)
    if change > 0:
        for j in range(3):
            velocity[unsafe_offset=j] += direction[unsafe_offset=j] * change


@export("mq_lightmap")
def lightmap(
    dst: Bytes, light: Words, width: Int32, height: Int32, stride: Int32, overbright: Int32
) abi("C"):
    for y in range(Int(height)):
        for x in range(Int(width)):
            var source = 4 * (y * Int(width) + x)
            var target = y * Int(stride) + 4 * x
            for c in range(3):
                var value = Int(UInt32(light[unsafe_offset=source + c])) >> (8 if overbright else 7)
                dst[unsafe_offset=target + c] = UInt8(min(255, max(0, value)))
            dst[unsafe_offset=target + 3] = 255


@export("mq_key_action")
def key_action(input_scan: Int32, menu: Int32) abi("C") -> Int32:
    # Physical USB scancodes are stable across Num Lock states.
    var scan = Int(input_scan)
    if scan == 98:
        return 1  # quit
    if scan == 85:
        return 2  # pause/menu
    if menu:
        if scan == 96:
            return 3
        if scan == 90:
            return 4
        if scan == 92:
            return 5
        if scan == 94:
            return 6
        if scan in (88, 93):
            return 7
        return 0
    if scan == 96:
        return 8
    if scan == 90:
        return 9
    if scan == 95:
        return 10
    if scan == 97:
        return 11
    if scan == 92:
        return 12
    if scan == 94:
        return 13
    if scan == 93:
        return 14
    if scan == 88:
        return 15
    if scan == 91:
        return 16
    if scan == 87:
        return 17
    if scan == 86:
        return 18
    if scan == 89:
        return 19
    if scan == 99:
        return 20
    return 0


@export("mq_fan")
def triangle_fan(indices: Shorts, base: Int32, vertices: Int32) abi("C"):
    for i in range(1, Int(vertices) - 1):
        var k = (i - 1) * 3
        indices[unsafe_offset=k] = UInt16(base)
        indices[unsafe_offset=k + 1] = UInt16(Int(base) + i)
        indices[unsafe_offset=k + 2] = UInt16(Int(base) + i + 1)


@export("mq_random")
def random_word(state: MutPointer[UInt32, MutUntrackedOrigin]) abi("C") -> Int32:
    # Game RNG is independent of graphics and the host C library.
    var x = state[unsafe_offset=0]
    x ^= x << 13
    x ^= x >> 17
    x ^= x << 5
    state[unsafe_offset=0] = x
    return Int32(x & 0x7FFFFFFF)


@export("mq_hash")
def state_hash(data: Bytes, count: Int32, seed: UInt32) abi("C") -> UInt32:
    var value = seed
    for i in range(Int(count)):
        value = (value ^ UInt32(data[unsafe_offset=i])) * UInt32(16777619)
    return value
