// One performance effect per physical pad, in reading order.
const LOOP_EFFECTS = [
  { name: "Low pass", filter: "lowpass", hz: 640, q: 0.7 },
  { name: "High pass", filter: "highpass", hz: 1400, q: 0.7 },
  { name: "Telephone", filter: "bandpass", hz: 1600, q: 1.7 },
  { name: "Auto wah", filter: "lowpass", hz: 1450, q: 5, sweep: 1100 },
  { name: "Drive", curve: (x) => Math.tanh(3 * x) * 0.6 },
  { name: "Fuzz", curve: (x) => Math.tanh(18 * x) * 0.4 },
  { name: "Crush", curve: (x) => Math.round(x * 10) / 10 },
  { name: "Wavefold", curve: (x) => Math.sin(9 * x) * 0.48 },
  { name: "Slapback", delay: 0.085, mix: 0.52, feedback: 0 },
  { name: "Dub echo", beats: 0.75, mix: 0.58, feedback: 0.44 },
  { name: "Flanger", delay: 0.0035, mix: 0.7, feedback: 0.52, sweep: 0.0025 },
  { name: "Chorus", delay: 0.019, mix: 0.65, feedback: 0, sweep: 0.004 },
  { name: "Tremolo", modulation: "sine", cycles: 2, center: 0.58, depth: 0.42 },
  { name: "Chop", modulation: "square", cycles: 4, center: 0.5, depth: 0.5 },
  { name: "Ring mod", modulation: "sine", hz: 82, center: 0, depth: 1 },
  { name: "Auto pan", modulation: "pan", cycles: 1, depth: 0.95 },
];

// Build only the selected branch. Its output fader also gates delay tails.
function makeLoopEffect(ctx, effect, bpm) {
  const input = ctx.createGain(),
    output = ctx.createGain();
  const nodes = [input, output];
  let oscillator;
  function modulate(param, hz, depth, wave = "sine") {
    oscillator = ctx.createOscillator();
    oscillator.type = wave;
    oscillator.frequency.value = hz;
    const amount = ctx.createGain();
    amount.gain.value = depth;
    oscillator.connect(amount).connect(param);
    nodes.push(oscillator, amount);
    oscillator.start();
  }
  if (effect.filter) {
    const filter = ctx.createBiquadFilter();
    filter.type = effect.filter;
    filter.frequency.value = effect.hz;
    filter.Q.value = effect.q;
    input.connect(filter).connect(output);
    nodes.push(filter);
    if (effect.sweep) modulate(filter.frequency, bpm / 60, effect.sweep);
  } else if (effect.curve) {
    const shaper = ctx.createWaveShaper();
    shaper.curve = Float32Array.from({ length: 2049 }, (_, i) =>
      effect.curve(i / 1024 - 1),
    );
    input.connect(shaper).connect(output);
    nodes.push(shaper);
  } else if (effect.delay || effect.beats) {
    const delay = ctx.createDelay(1),
      wet = ctx.createGain(),
      direct = ctx.createGain();
    delay.delayTime.value = effect.delay ?? (effect.beats * 60) / bpm;
    wet.gain.value = effect.mix;
    direct.gain.value = 0.78;
    input.connect(direct).connect(output);
    input.connect(delay).connect(wet).connect(output);
    nodes.push(delay, wet, direct);
    if (effect.feedback) {
      const feedback = ctx.createGain();
      feedback.gain.value = effect.feedback;
      delay.connect(feedback).connect(delay);
      nodes.push(feedback);
    }
    if (effect.sweep) modulate(delay.delayTime, bpm / 240, effect.sweep);
  } else if (effect.modulation === "pan") {
    const pan = ctx.createStereoPanner();
    input.connect(pan).connect(output);
    nodes.push(pan);
    modulate(pan.pan, (effect.cycles * bpm) / 60, effect.depth);
  } else {
    const amplitude = ctx.createGain();
    amplitude.gain.value = effect.center;
    input.connect(amplitude).connect(output);
    nodes.push(amplitude);
    modulate(
      amplitude.gain,
      effect.hz ?? (effect.cycles * bpm) / 60,
      effect.depth,
      effect.modulation,
    );
  }
  return {
    input,
    output,
    dispose() {
      oscillator?.stop();
      for (const node of nodes) node.disconnect();
    },
  };
}
