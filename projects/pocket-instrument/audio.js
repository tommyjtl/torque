// Linux browser preview. Playback and the sequencer share the AudioContext clock.
const DEFAULT_PITCH = 0;
const DEFAULT_LEVEL = 50;

class SamplerAudio {
  constructor() {
    this.factory = new Map();
    this.samples = new Map();
    this.pitch = Array.from({ length: 16 }, () =>
      Array(16).fill(DEFAULT_PITCH),
    );
    this.level = Array(16).fill(DEFAULT_LEVEL);
    this.effectPad = null;
    this.effectBranch = null;
    this.voices = new Map();
  }

  async unlock() {
    if (!this.context) {
      this.context = new AudioContext({ latencyHint: "interactive" });
      this.loopInput = this.context.createGain();
      this.dry = this.context.createGain();
      this.output = this.context.createDynamicsCompressor();
      this.loopInput.connect(this.dry).connect(this.output);
      this.output.connect(this.context.destination);
      this.meter = this.context.createAnalyser();
      this.meter.fftSize = 2048;
      this.meterSamples = new Float32Array(this.meter.fftSize);
      this.output.connect(this.meter);
    }
    if (this.context.state !== "running") await this.context.resume();
  }

  outputPeak() {
    if (this.context?.state !== "running") return 0;
    this.meter.getFloatTimeDomainData(this.meterSamples);
    let peak = 0;
    for (const sample of this.meterSamples)
      peak = Math.max(peak, Math.abs(sample));
    return peak;
  }

  setEffect(pad, bpm) {
    if (this.effectPad === pad) return;
    const ctx = this.context;
    const now = ctx.currentTime;
    const old = this.effectBranch;
    if (old) {
      old.output.gain.setTargetAtTime(0, now, 0.003);
      setTimeout(() => {
        this.loopInput.disconnect(old.input);
        old.dispose();
      }, 40);
    }
    this.effectPad = pad;
    this.effectBranch = null;
    this.dry.gain.setTargetAtTime(pad === null ? 1 : 0, now, 0.003);
    if (pad === null) return;
    const branch = makeLoopEffect(ctx, LOOP_EFFECTS[pad], bpm);
    branch.output.gain.value = 0;
    this.loopInput.connect(branch.input);
    branch.output.connect(this.output);
    branch.output.gain.setTargetAtTime(1, now, 0.003);
    this.effectBranch = branch;
  }

  // Original procedurally generated PCM. Cache the drum pieces and melodic roots.
  source(slot, pad) {
    if (this.samples.has(slot)) return this.samples.get(slot);
    const key = slot * 16 + (slot < 8 ? 0 : pad);
    if (this.factory.has(key)) return this.factory.get(key);
    const sr = 22050;
    const type = pad % 8;
    const length =
      slot < 8 ? 0.65 : [0.32, 0.19, 0.075, 0.21, 0.28, 0.08, 0.23, 0.4][type];
    const buf = this.context.createBuffer(1, Math.ceil(sr * length), sr);
    const out = buf.getChannelData(0);
    let seed = key + 1,
      prev = 0,
      phase = 0;
    const tuning = 1 + (slot % 8) * 0.09 + (pad >= 8 && slot >= 8 ? 0.38 : 0);
    for (let i = 0; i < out.length; i++) {
      const t = i / sr,
        frac = t / length;
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      const noise = seed / 2147483648 - 1,
        hiss = (noise - prev) * 0.5;
      prev = noise;
      let wave;
      if (slot < 8) {
        phase += (2 * Math.PI * (130.81 * (slot === 1 ? 0.5 : 1))) / sr;
        wave = 0.7 * Math.sin(phase) + 0.3 * Math.sin(phase * (slot + 2));
      } else {
        const freq = [
          46 + 130 * Math.exp(-t * 35),
          171,
          3100,
          1250,
          99 + 110 * Math.exp(-t * 14),
          820,
          540,
          2400,
        ][type];
        phase += (2 * Math.PI * freq * tuning) / sr;
        const tone = Math.sin(phase);
        wave = [
          tone,
          0.35 * tone + 0.85 * noise,
          hiss,
          noise * (0.35 + 0.65 * Math.abs(Math.sin(85 * t))),
          tone,
          0.8 * tone + 0.2 * noise,
          tone * Math.cos(phase * 1.49),
          hiss,
        ][type];
      }
      out[i] =
        wave *
        Math.min(1, t * 950) *
        Math.exp(-4 * frac) *
        Math.min(1, (1 - frac) * 30);
    }
    this.factory.set(key, buf);
    return buf;
  }

  tunePad(slot, pad, semitones) {
    this.pitch[slot][pad] = semitones;
    for (const [source, voice] of this.voices) {
      if (voice.slot === slot && voice.pad === pad) {
        source.detune.setTargetAtTime(
          semitones * 100,
          this.context.currentTime,
          0.005,
        );
      }
    }
  }

  play(slot, pad, when) {
    const ctx = this.context;
    if (!ctx || ctx.state !== "running") return;
    const buffer = this.source(slot, pad);
    const sliced = this.samples.has(slot);
    const source = ctx.createBufferSource(),
      gain = ctx.createGain();
    const first = sliced ? Math.floor((pad * buffer.length) / 16) : 0;
    const end = sliced
      ? Math.floor(((pad + 1) * buffer.length) / 16)
      : buffer.length;
    const offset = first / buffer.sampleRate;
    const duration = (end - first) / buffer.sampleRate;
    source.buffer = buffer;
    source.playbackRate.value = !sliced && slot < 8 ? 2 ** (pad / 12) : 1;
    source.detune.value = this.pitch[slot][pad] * 100;
    gain.gain.value = (0.42 * this.level[slot]) / 100;
    // Scheduled pattern voices share the FX bus. Live auditions go directly to the mix.
    source
      .connect(gain)
      .connect(when === undefined ? this.output : this.loopInput);
    source.onended = () => {
      this.voices.delete(source);
      source.disconnect();
      gain.disconnect();
    };
    const startTime = when ?? ctx.currentTime;
    source.start(startTime, offset, duration);
    this.voices.set(source, {
      slot,
      pad,
      startTime,
      audible: gain.gain.value > 0,
    });
  }

  silence() {
    for (const voice of this.voices.keys()) voice.stop();
    this.voices.clear();
  }

  remaining(slot) {
    return Math.max(
      0,
      40 -
        [...this.samples].reduce(
          (sum, [i, buf]) => sum + (i === slot ? 0 : buf.duration),
          0,
        ),
    );
  }
}
