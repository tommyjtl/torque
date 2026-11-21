"""QuakeC v6 bytecode execution for the original id1 program (GPL-2.0-or-later)."""
from std.ffi import external_call
from std.memory import MutPointer
from std.origin import MutUntrackedOrigin

comptime Words = MutPointer[Int32, MutUntrackedOrigin]
comptime Floats = MutPointer[Float32, MutUntrackedOrigin]
comptime Shorts = MutPointer[UInt16, MutUntrackedOrigin]
comptime Bytes = MutPointer[UInt8, MutUntrackedOrigin]


def branch(offset: Int) -> Int:
    return Int(Int16(UInt16(offset)))


def operand_width(op: Int, operand: Int) -> Int:
    # Branch displacements are signed immediates; all other references are
    # unsigned word offsets. Return copies three words even for scalar values.
    if op == 61:
        return 0
    if op == 49 or op == 50 or 51 <= op <= 59:
        return 1 if operand == 0 else 0
    if op == 0 or op == 43:
        return 3 if operand == 0 else 0
    if op == 60:
        return 1 if operand < 2 else 0
    if 44 <= op <= 48:
        return (3 if op == 45 else 1) if operand == 0 else (1 if operand == 2 else 0)
    if 31 <= op <= 42:
        if operand == 2:
            return 0
        return 3 if op == 32 or (op == 38 and operand == 0) else 1
    if op == 2 or op == 11 or op == 16:
        return 3 if operand < 2 else 1
    if op == 3:
        return 1 if operand == 0 else 3
    if op == 4:
        return 1 if operand == 1 else 3
    if op == 7 or op == 9 or (op == 25 and operand == 2):
        return 3
    return 1


@export("mq_validate_code")
def validate(st: Shorts, count: Int32, globals_count: Int32) abi("C") -> Int32:
    for pc in range(Int(count)):
        var k = pc * 4
        var op = Int(st[unsafe_offset=k])
        if op > 65:
            return Int32(pc + 1)
        for operand in range(3):
            var width = operand_width(op, operand)
            var raw = Int(st[unsafe_offset=k + 1 + operand])
            if width and raw + width > Int(globals_count):
                return Int32(pc + 1)
        if op in (49, 50, 61):
            var delta = Int(st[unsafe_offset=k + (1 if op == 61 else 2)])
            if not (0 <= pc + branch(delta) < Int(count)):
                return Int32(pc + 1)
    return 0


@export("mq_execute")
def execute(
    st: Shorts, g: Words, f: Floats, start: Int32, count: Int32, floor_depth: Int32
) abi("C") -> Int32:
    var pc = Int(start)
    for instruction in range(1000000):
        if not (0 <= pc < Int(count)):
            return -1
        var k = 4 * pc
        var op = Int(st[unsafe_offset=k])
        var a = Int(st[unsafe_offset=k + 1])
        var b = Int(st[unsafe_offset=k + 2])
        var c = Int(st[unsafe_offset=k + 3])
        external_call["mq_statement", NoneType](Int32(pc))
        pc += 1
        if op == 0 or op == 43:
            for i in range(3):
                g[unsafe_offset=1 + i] = g[unsafe_offset=a + i]
            pc = Int(external_call["mq_return", Int32](floor_depth))
            if pc < 0:
                return Int32(instruction + 1)
        elif op == 1:
            f[unsafe_offset=c] = f[unsafe_offset=a] * f[unsafe_offset=b]
        elif op == 2:
            var dot = Float32(0)
            for j in range(3):
                dot += f[unsafe_offset=a + j] * f[unsafe_offset=b + j]
            f[unsafe_offset=c] = dot
        elif op == 3 or op == 4:
            for j in range(3):
                f[unsafe_offset=c + j] = (
                    f[unsafe_offset=a + (j if op == 4 else 0)]
                    * f[unsafe_offset=b + (j if op == 3 else 0)]
                )
        elif op == 5:
            f[unsafe_offset=c] = f[unsafe_offset=a] / f[unsafe_offset=b]
        elif op in (6, 7, 8, 9):
            var width = 3 if op in (7, 9) else 1
            for j in range(width):
                var left = f[unsafe_offset=a + j]
                var right = f[unsafe_offset=b + j]
                f[unsafe_offset=c + j] = left + right if op <= 7 else left - right
        elif 10 <= op <= 19:
            var kind = (op - 10) % 5
            var same: Bool
            if kind == 0:
                same = f[unsafe_offset=a] == f[unsafe_offset=b]
            elif kind == 1:
                same = True
                for j in range(3):
                    if f[unsafe_offset=a + j] != f[unsafe_offset=b + j]:
                        same = False
            elif kind == 2:
                var cmp = external_call["mq_string_compare", Int32](
                    g[unsafe_offset=a], g[unsafe_offset=b]
                )
                if op == 17:
                    f[unsafe_offset=c] = Float32(cmp)
                    continue
                same = cmp == 0
            else:
                same = g[unsafe_offset=a] == g[unsafe_offset=b]
            f[unsafe_offset=c] = Float32(Int(same if op < 15 else not same))
        elif 20 <= op <= 23:
            var x = f[unsafe_offset=a]
            var y = f[unsafe_offset=b]
            var result = (
                x <= y if op == 20 else x >= y if op == 21 else x < y if op == 22 else x > y
            )
            f[unsafe_offset=c] = Float32(Int(result))
        elif 24 <= op <= 30:
            var width = 3 if op == 25 else 1
            var addr = external_call["mq_field_address", Int32](
                g[unsafe_offset=a], g[unsafe_offset=b], Int32(width), Int32(op == 30)
            )
            if op == 30:
                g[unsafe_offset=c] = addr
            else:
                var field = external_call["mq_entity_words", Words](addr, Int32(width))
                for j in range(width):
                    g[unsafe_offset=c + j] = field[unsafe_offset=j]
        elif 31 <= op <= 36:
            for j in range(3 if op == 32 else 1):
                g[unsafe_offset=b + j] = g[unsafe_offset=a + j]
        elif 37 <= op <= 42:
            var width = 3 if op == 38 else 1
            var field = external_call["mq_entity_words", Words](g[unsafe_offset=b], Int32(width))
            for j in range(width):
                field[unsafe_offset=j] = g[unsafe_offset=a + j]
        elif 44 <= op <= 48:
            var zero: Bool
            if op == 44:
                zero = f[unsafe_offset=a] == 0
            elif op == 45:
                zero = (
                    f[unsafe_offset=a] == 0
                    and f[unsafe_offset=a + 1] == 0
                    and f[unsafe_offset=a + 2] == 0
                )
            elif op == 46:
                zero = external_call["mq_string_compare", Int32](g[unsafe_offset=a], Int32(0)) == 0
            else:
                zero = g[unsafe_offset=a] == 0
            f[unsafe_offset=c] = Float32(Int(zero))
        elif op in (49, 50):
            if (g[unsafe_offset=a] != 0) == (op == 49):
                pc += branch(b) - 1
        elif 51 <= op <= 59:
            var target = external_call["mq_call", Int32](g[unsafe_offset=a], Int32(op - 51))
            if target >= 0:
                pc = Int(target)
        elif op == 60:
            external_call["mq_state", NoneType](f[unsafe_offset=a], g[unsafe_offset=b])
        elif op == 61:
            pc += branch(a) - 1
        elif op == 62 or op == 63:
            var a_true = f[unsafe_offset=a] != 0
            var b_true = f[unsafe_offset=b] != 0
            f[unsafe_offset=c] = Float32(
                Int((a_true and b_true) if op == 62 else (a_true or b_true))
            )
        elif op == 64 or op == 65:
            var x = Int32(f[unsafe_offset=a])
            var y = Int32(f[unsafe_offset=b])
            f[unsafe_offset=c] = Float32(x & y if op == 64 else x | y)
        else:
            return -2
    return -3


@export("mq_push_frame")
def push_frame(
    frames: Words,
    depth: Words,
    stack_limit: Int32,
    locals: Words,
    used: Words,
    locals_limit: Int32,
    globals: Words,
    globals_count: Int32,
    caller: Int32,
    pc: Int32,
    start: Int32,
    count: Int32,
    parameters: Bytes,
    parameter_count: Int32,
) abi("C") -> Int32:
    """Save the caller before overwriting the callee's globals with arguments."""
    var level = Int(depth[unsafe_offset=0])
    var top = Int(used[unsafe_offset=0])
    var base = Int(start)
    var length = Int(count)
    if level < 0 or level + 1 >= Int(stack_limit) or top < 0 or length < 0:
        return 0
    if top + length > Int(locals_limit) or base < 0 or base + length > Int(globals_count):
        return 0
    if parameter_count < 0 or parameter_count > 8:
        return 0
    var end = base
    for i in range(Int(parameter_count)):
        var width = Int(parameters[unsafe_offset=i])
        if width > 3:
            return 0
        end += width
    if end > Int(globals_count):
        return 0
    frames[unsafe_offset=2 * level] = pc
    frames[unsafe_offset=2 * level + 1] = caller
    for i in range(length):
        locals[unsafe_offset=top + i] = globals[unsafe_offset=base + i]
    var offset = base
    for i in range(Int(parameter_count)):
        for j in range(Int(parameters[unsafe_offset=i])):
            globals[unsafe_offset=offset] = globals[unsafe_offset=4 + 3 * i + j]
            offset += 1
    depth[unsafe_offset=0] += 1
    used[unsafe_offset=0] += count
    return 1


@export("mq_pop_frame")
def pop_frame(
    frames: Words,
    depth: Words,
    locals: Words,
    used: Words,
    globals: Words,
    start: Int32,
    count: Int32,
    caller: Words,
    pc: Words,
) abi("C") -> Int32:
    var level = Int(depth[unsafe_offset=0]) - 1
    var top = Int(used[unsafe_offset=0]) - Int(count)
    if level < 0 or top < 0:
        return 0
    for i in range(Int(count)):
        globals[unsafe_offset=Int(start) + i] = locals[unsafe_offset=top + i]
    depth[unsafe_offset=0] -= 1
    used[unsafe_offset=0] -= count
    caller[unsafe_offset=0] = frames[unsafe_offset=2 * level + 1]
    pc[unsafe_offset=0] = frames[unsafe_offset=2 * level]
    return 1
