"""B.A.P. native polyphonic sampler. The SDL callback calls bap_render directly."""
from std.math import sin, tan, tanh, abs, max, min, sqrt
from std.memory import MutPointer
from std.origin import MutUntrackedOrigin

comptime I = MutPointer[Int32, MutUntrackedOrigin]
comptime F = MutPointer[Float32, MutUntrackedOrigin]
comptime RATE = 48000
comptime TAKE = RATE * 8
comptime VOICES = 24


# s: selected slot, note, bpm, transport, pattern, playhead, held FX,
# next voice, sounding pads, peak (0..1000), previous FX, delay cursor, valid history.
# Per voice: slot+1, note, PCM offset, sample count, recorded flag, sequenced flag.
# Per voice floats: source position, playback increment, amplitude.
# dsp: sequencer countdown, LFO phase, filter states, wet envelope.
@export("bap_strike")
def strike(
    s: I,
    info: I,
    lengths: I,
    offsets: I,
    sizes: I,
    pitches: I,
    levels: I,
    voice: F,
    slot: Int32,
    note: Int32,
    sequence: Int32,
) abi("C"):
    var v = Int(s[unsafe_offset=7])
    for k in range(VOICES):
        var j = (v + k) % VOICES
        if info[unsafe_offset=6 * j] == 0:
            v = j
            break
    s[unsafe_offset=7] = Int32((v + 1) % VOICES)
    var j = Int(slot) * 16 + Int(note)
    var n = Int(lengths[unsafe_offset=Int(slot)])
    var offset = offsets[unsafe_offset=j]
    var count = sizes[unsafe_offset=j]
    var base = Float32(22050.0 / 48000.0)
    var semis = Int(pitches[unsafe_offset=j])
    if n > 0:
        var begin = n * Int(note) // 16
        offset = Int32(Int(slot) * TAKE + begin)
        count = Int32(n * (Int(note) + 1) // 16 - begin)
        base = 1
    elif slot < 8:
        semis += Int(note)
    info[unsafe_offset=6 * v] = slot + 1
    info[unsafe_offset=6 * v + 1] = note
    info[unsafe_offset=6 * v + 2] = offset
    info[unsafe_offset=6 * v + 3] = count
    info[unsafe_offset=6 * v + 4] = Int32(n > 0)
    info[unsafe_offset=6 * v + 5] = sequence
    voice[unsafe_offset=3 * v] = 0
    voice[unsafe_offset=3 * v + 1] = base * Float32(2) ** (Float32(semis) / 12)
    voice[unsafe_offset=3 * v + 2] = (
        Float32(levels[unsafe_offset=Int(slot)]) * 0.0042
    )


@export("bap_render")
def render(
    s: I,
    info: I,
    lengths: I,
    offsets: I,
    sizes: I,
    pitches: I,
    levels: I,
    steps: I,
    voice: F,
    dsp: F,
    factory: F,
    takes: F,
    delay: F,
    output: F,
    frames: Int32,
) abi("C"):
    var fx = Int(s[unsafe_offset=6])
    var bpm = Float32(s[unsafe_offset=2])
    var interval = 720000 / bpm
    if fx >= 0 and fx != Int(s[unsafe_offset=10]):
        dsp[unsafe_offset=1] = 0
        dsp[unsafe_offset=2] = 0
        dsp[unsafe_offset=3] = 0
        dsp[unsafe_offset=4] = 0
        s[unsafe_offset=12] = 0
        s[unsafe_offset=10] = Int32(fx)
    var processing = Int(s[unsafe_offset=10])
    var peak = Float32(0)
    var mask = 0
    for frame in range(Int(frames)):
        if s[unsafe_offset=3] != 0:
            if dsp[unsafe_offset=0] <= 0:
                var h = (Int(s[unsafe_offset=5]) + 1) % 16
                s[unsafe_offset=5] = Int32(h)
                for slot in range(16):
                    var note = steps[
                        unsafe_offset=(Int(s[unsafe_offset=4]) * 16 + slot) * 16
                        + h
                    ]
                    if note >= 0:
                        strike(
                            s,
                            info,
                            lengths,
                            offsets,
                            sizes,
                            pitches,
                            levels,
                            voice,
                            Int32(slot),
                            note,
                            1,
                        )
                dsp[unsafe_offset=0] += interval
            dsp[unsafe_offset=0] -= 1
        var live = Float32(0)
        var loop = Float32(0)
        for v in range(VOICES):
            var k = 6 * v
            var slot = info[unsafe_offset=k] - 1
            if slot < 0:
                continue
            var pos = voice[unsafe_offset=3 * v]
            var n = Int(info[unsafe_offset=k + 3])
            if Int(pos) >= n:
                info[unsafe_offset=k] = 0
                continue
            var i = Int(pos)
            var offset = Int(info[unsafe_offset=k + 2])
            var pcm = factory
            if info[unsafe_offset=k + 4] != 0:
                pcm = takes
            var a = pcm[unsafe_offset=offset + i]
            var b = pcm[unsafe_offset=offset + min(n - 1, i + 1)]
            var sample = (a + (b - a) * (pos - Float32(i))) * voice[
                unsafe_offset=3 * v + 2
            ]
            if info[unsafe_offset=k + 5] != 0:
                loop += sample
            else:
                live += sample
            if (
                slot == s[unsafe_offset=0]
                and voice[unsafe_offset=3 * v + 2] > 0
            ):
                mask |= 1 << Int(info[unsafe_offset=k + 1])
            voice[unsafe_offset=3 * v] = pos + voice[unsafe_offset=3 * v + 1]
        var l = loop
        var r = loop
        var wet = dsp[unsafe_offset=4]
        if fx >= 0 or wet > 0.0001:
            var x = loop
            var phase = dsp[unsafe_offset=1]
            var rate = bpm / 60
            var p = processing
            if p <= 3:
                var freq = Float32(640)
                var q = Float32(0.7)
                if p == 1:
                    freq = 1400
                elif p == 2:
                    freq = 1600
                    q = 1.7
                elif p == 3:
                    freq = 1450 + 1100 * sin(phase)
                    q = 5
                var g = tan(Float32(3.14159265 / 48000) * freq)
                var hp = (
                    loop
                    - (1 / q + g) * dsp[unsafe_offset=2]
                    - dsp[unsafe_offset=3]
                ) / (1 + g * (g + 1 / q))
                var bp = g * hp + dsp[unsafe_offset=2]
                var lp = g * bp + dsp[unsafe_offset=3]
                dsp[unsafe_offset=2] = g * hp + bp
                dsp[unsafe_offset=3] = g * bp + lp
                x = hp if p == 1 else (bp / q if p == 2 else lp)
            elif p == 4 or p == 5:
                x = tanh(loop * Float32(18 if p == 5 else 3)) * Float32(
                    0.4 if p == 5 else 0.6
                )
            elif p == 6:
                x = (
                    Float32(
                        Int(loop * 10 + Float32(0.5 if loop >= 0 else -0.5))
                    )
                    / 10
                )
            elif p == 7:
                x = sin(loop * 9) * 0.48
            elif p <= 11:
                var t = Float32(0.085)
                var feedback = Float32(0)
                var mix = Float32(0.52)
                if p == 9:
                    t = 45 / bpm
                    feedback = 0.44
                    mix = 0.58
                elif p == 10 or p == 11:
                    rate *= 0.25
                    t = (0.0035 + 0.0025 * sin(phase)) if p == 10 else (
                        0.019 + 0.004 * sin(phase)
                    )
                    feedback = 0.52 if p == 10 else 0
                    mix = 0.7
                var cursor = Int(s[unsafe_offset=11])
                var distance = t * 48000
                var whole = Int(distance)
                var echo = Float32(0)
                if Int(s[unsafe_offset=12]) > whole:
                    var j = (cursor - whole + RATE) % RATE
                    echo = delay[unsafe_offset=j] + (
                        distance - Float32(whole)
                    ) * (
                        delay[unsafe_offset=(j + RATE - 1) % RATE]
                        - delay[unsafe_offset=j]
                    )
                delay[unsafe_offset=cursor] = loop + echo * feedback
                s[unsafe_offset=11] = Int32((cursor + 1) % RATE)
                s[unsafe_offset=12] = min(Int32(RATE), s[unsafe_offset=12] + 1)
                x = 0.78 * loop + echo * mix
            elif p == 12:
                rate *= 2
                x = loop * (0.58 + 0.42 * sin(phase))
            elif p == 13:
                rate *= 4
                x = loop if phase < 3.14159265 else 0
            elif p == 14:
                rate = 82
                x = loop * sin(phase)
            var target = Float32(1) if fx >= 0 else Float32(0)
            wet += (target - wet) * 0.007
            dsp[unsafe_offset=4] = wet
            l = loop + (x - loop) * wet
            r = l
            if p == 15:
                var pan = 0.95 * sin(phase)
                l = loop * (1 + wet * (sqrt(1 - pan) - 1))
                r = loop * (1 + wet * (sqrt(1 + pan) - 1))
            phase += rate * Float32(6.2831853 / 48000)
            dsp[unsafe_offset=1] = (
                phase - 6.2831853 if phase >= 6.2831853 else phase
            )
            if fx < 0 and wet <= 0.0001:
                s[unsafe_offset=10] = -1
        l = max(Float32(-1), min(Float32(1), l + live))
        r = max(Float32(-1), min(Float32(1), r + live))
        output[unsafe_offset=2 * frame] = l
        output[unsafe_offset=2 * frame + 1] = r
        peak = max(peak, max(abs(l), abs(r)))
    s[unsafe_offset=8] = Int32(mask)
    s[unsafe_offset=9] = Int32(peak * 1000)
