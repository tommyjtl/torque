"use strict";
const $ = (selector) => document.querySelector(selector);
const fmt = (n) => String(n).padStart(2, "0");
const clip = (n, min, max) => Math.min(max, Math.max(min, n));
// Relative shaft positions are independent of the parameter ranges.
const encoderAngles = { a: 0, b: 0 };
const physical = [
  "Digit1",
  "Digit2",
  "NumpadDivide",
  "NumpadMultiply",
  "KeyQ",
  "Numpad7",
  "Numpad8",
  "Numpad9",
  "KeyA",
  "Numpad4",
  "Numpad5",
  "Numpad6",
  "KeyZ",
  "Numpad1",
  "Numpad2",
  "Numpad3",
];
const laptop = [
  "Digit1",
  "Digit2",
  "Digit3",
  "Digit4",
  "KeyQ",
  "KeyW",
  "KeyE",
  "KeyR",
  "KeyA",
  "KeyS",
  "KeyD",
  "KeyF",
  "KeyZ",
  "KeyX",
  "KeyC",
  "KeyV",
];
const names = [
  "Glass keys",
  "Sub bass",
  "Bell tone",
  "Wire pluck",
  "Soft tine",
  "Reed",
  "Overtone",
  "Pulse",
  "Break kit",
  "Dust kit",
  "Metal kit",
  "Click kit",
  "Block kit",
  "Tape kit",
  "Bright kit",
  "Chip kit",
];
const kitPieces = [
  "Kick",
  "Snare",
  "Hat",
  "Clap",
  "Tom",
  "Rim",
  "Bell",
  "Ride",
];
function noteName(slot, note) {
  if (audio.samples.has(slot)) return "SLICE " + fmt(note + 1);
  if (slot < 8) {
    const offset = note + audio.pitch[slot][note];
    const midi = (slot === 1 ? 36 : 48) + offset;
    const names = [
      "C",
      "C♯",
      "D",
      "D♯",
      "E",
      "F",
      "F♯",
      "G",
      "G♯",
      "A",
      "A♯",
      "B",
    ];
    return names[midi % 12] + (Math.floor(midi / 12) - 1);
  }
  return kitPieces[note % 8].toUpperCase() + (note >= 8 ? " II" : "");
}
const audio = new SamplerAudio();
const patterns = Array.from({ length: 16 }, () =>
  Array.from({ length: 16 }, () => Array(16).fill(-1)),
);
const groove = [0, -1, 2, -1, 1, -1, 2, 2, 0, -1, 2, 0, 1, -1, 2, 3];
patterns[0][8] = groove.slice();
const DEFAULT_BPM = 96;
const state = {
  slot: 8,
  pattern: 0,
  bpm: DEFAULT_BPM,
  note: 0,
  write: false,
  mode: "",
  dial: "a",
  playing: false,
  head: -1,
  message: "",
};
let nextBeat = 0,
  nextTime = 0,
  timer,
  frames = [],
  messageTimer,
  pendingPlay = 0;
let recording = null;
let auditionEpoch = 0;
const editFlashes = new Map();
const fxModifiers = new Set();
const fxHolds = new Map();
const padMode = () => (fxModifiers.size ? "fx" : state.mode);
const padButtons = physical.map((_, i) => {
  const el = document.createElement("button");
  el.className = "pad";
  el.setAttribute("aria-label", "Pad " + (i + 1));
  el.innerHTML = `<i class="switch" aria-hidden="true"></i><span class="legend"><strong>${i + 1}</strong></span>`;
  let fxPointer = false;
  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    fxPointer = fxModifiers.size > 0;
    if (fxPointer) {
      el.setPointerCapture(e.pointerId);
      holdFx(e.pointerId, i);
    }
  });
  for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) {
    el.addEventListener(event, (e) => releaseFx(e.pointerId));
  }
  el.addEventListener("click", (e) => {
    if (e.detail && fxPointer) return;
    pad(i);
  });
  $("#pads").append(el);
  return el;
});
const strip = $("#strip");
const meterFloor = Number(strip.getAttribute("aria-valuemin"));
let meterDb = meterFloor;
let meterTimer;
let showingParameter = false;
function paintMeter(label, value, min, max, text) {
  strip.style.setProperty("--fill", ((value - min) * 100) / (max - min) + "%");
  strip.setAttribute("aria-label", label);
  strip.setAttribute("aria-valuemin", String(min));
  strip.setAttribute("aria-valuemax", String(max));
  strip.setAttribute("aria-valuenow", String(value));
  strip.setAttribute("aria-valuetext", text);
}
function paintOutputMeter() {
  paintMeter(
    "Output level",
    meterDb,
    meterFloor,
    0,
    meterDb === meterFloor ? "Silent" : meterDb + " dBFS",
  );
}

// Sample the same voice registry the audio engine uses for tuning and cleanup.
function updatePadLights() {
  const mode = padMode();
  const sounding = new Set();
  if (
    !state.write &&
    (!mode || mode === "bpm") &&
    audio.context?.state === "running"
  ) {
    const now = audio.context.currentTime;
    for (const voice of audio.voices.values()) {
      if (voice.audible && voice.slot === state.slot && voice.startTime <= now)
        sounding.add(voice.pad);
    }
  }
  padButtons.forEach((button, i) => {
    const playhead = state.playing && state.write && !mode && i === state.head;
    button.classList.toggle(
      "hit",
      !recording &&
        (sounding.has(i) ||
          (mode !== "record" && editFlashes.has(i)) ||
          playhead),
    );
  });
}

function updateOutputMeter() {
  updatePadLights();
  const peakDb = Math.round(20 * Math.log10(audio.outputPeak()));
  // Catch transients immediately and release by two LCD ticks per update.
  const nextDb = clip(Math.max(peakDb, meterDb - 2), meterFloor, 0);
  if (nextDb !== meterDb) {
    meterDb = nextDb;
    if (!showingParameter) paintOutputMeter();
  }
  if (meterDb === meterFloor && !audio.voices.size && !state.playing) {
    clearInterval(meterTimer);
    meterTimer = undefined;
  }
}

function startOutputMeter() {
  if (meterTimer === undefined) meterTimer = setInterval(updateOutputMeter, 33);
}

for (const effect of LOOP_EFFECTS) {
  const item = document.createElement("li");
  item.textContent = effect.name;
  $("#fx-map").append(item);
}
const gear = [...document.querySelectorAll("[data-action]")];
const getButton = (name) => gear.find((b) => b.dataset.action === name);
// Each illustration occupies a fixed electrode on the simulated LCD.
const comicFrames = [
  ["dazed", "bounce", "guard", "win", "tumble"],
  ["dazed", "bounce", "guard"],
  ["jab", "duck", "tumble"],
  ["dazed", "jab", "recoil"],
  ["bounce", "duck", "win"],
  ["jab", "guard"],
  ["recoil", "win", "tumble"],
  ["dazed", "win", "tumble"],
];
const comicSegments = [...document.querySelectorAll(".scene [data-pose]")];
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
let comicOffset = 0,
  displayedFrame = -1;
function drawDisplay() {
  const step =
    state.playing && state.head >= 0
      ? Math.floor(state.head / (state.bpm > 120 ? 4 : 2))
      : 0;
  const frame = reducedMotion.matches
    ? 0
    : (step + comicOffset) % comicFrames.length;
  if (frame !== displayedFrame) {
    comicSegments.forEach((segment) =>
      segment.classList.toggle(
        "lit",
        comicFrames[frame].includes(segment.dataset.pose),
      ),
    );
    displayedFrame = frame;
  }
}
function render() {
  if (showingParameter && (!state.message || recording)) {
    showingParameter = false;
    paintOutputMeter();
  }
  const s = state,
    lane = patterns[s.pattern][s.slot],
    bpmMode = s.mode === "bpm";
  const mode = padMode();
  const choosingRecordSlot = mode === "record";
  $("#pads").classList.toggle("record-slots", choosingRecordSlot);
  if (choosingRecordSlot) {
    $("#bank").textContent = audio.samples.size + "/16 RECORDED";
    $("#soundName").textContent = audio.samples.size
      ? "Orange = take"
      : "All factory";
  } else if (recording) {
    $("#bank").textContent = "REC / " + fmt(recording.slot + 1);
    $("#soundName").textContent =
      recording.status === "RECORDING"
        ? recording.secondsLeft + "s left"
        : "Sample " + fmt(recording.slot + 1);
  } else {
    const recorded = audio.samples.has(s.slot);
    const bank = recorded ? "SLICE" : s.slot < 8 ? "MELO" : "DRUM";
    $("#bank").textContent = bank + " / " + fmt(s.slot + 1);
    $("#soundName").textContent = recorded
      ? "Sample " + fmt(s.slot + 1)
      : names[s.slot];
  }
  $("#tempo").textContent = String(s.bpm).padStart(3, "0");
  $("#patternNo").textContent = fmt(s.pattern + 1);
  const prompts = {
    sound: "SELECT SOUND",
    pattern: "SELECT PATTERN",
    bpm: "SET TEMPO",
    record: "REC → SLOT",
    fx:
      audio.effectPad !== null
        ? LOOP_EFFECTS[audio.effectPad].name.toUpperCase()
        : s.playing
          ? "FX · HOLD PAD"
          : "FX · PRESS PLAY",
  };
  $("#status").textContent = recording
    ? recording.status
    : s.message ||
      prompts[mode] ||
      (s.write
        ? "WRITE · " + noteName(s.slot, s.note)
        : s.playing
          ? "PLAYING"
          : "READY");
  const selected =
    mode === "sound" ? s.slot : mode === "pattern" ? s.pattern : -1;
  const heldPads = new Set(fxHolds.values());
  padButtons.forEach((b, i) => {
    const occupied = choosingRecordSlot && audio.samples.has(i);
    const label = "Pad " + (i + 1);
    const capturing = recording?.status === "RECORDING" && recording.slot === i;
    b.classList.toggle("capturing", capturing);
    b.setAttribute(
      "aria-label",
      capturing
        ? label + ", recording"
        : choosingRecordSlot
          ? label + (occupied ? ", recorded" : ", factory sound")
          : mode === "fx"
            ? label + ", " + LOOP_EFFECTS[i].name
            : label,
    );
    const lit = recording
      ? capturing
      : occupied ||
        heldPads.has(i) ||
        selected === i ||
        (!mode && s.write && lane[i] >= 0);
    b.classList.toggle("on", lit);
    b.setAttribute("aria-pressed", String(lit));
  });
  updatePadLights();
  gear.forEach((b) => {
    const a = b.dataset.action;
    const on =
      a === s.dial ||
      a === mode ||
      (a === "write" && s.write) ||
      (a === "play" && s.playing) ||
      (a === "record" && !!recording);
    b.setAttribute("aria-pressed", String(on));
  });
  getButton("a").setAttribute(
    "aria-label",
    bpmMode ? "Knob A tempo" : "Knob A pitch",
  );
  for (const dial of ["a", "b"]) {
    getButton(dial).firstElementChild.style.setProperty(
      "--angle",
      encoderAngles[dial] + "deg",
    );
  }
  getButton("play").querySelector("em").textContent = s.playing
    ? "stop"
    : "play";
  getButton("play").setAttribute("aria-label", s.playing ? "Stop" : "Play");
  drawDisplay();
}
function message(value, meter = null) {
  if (meter) {
    showingParameter = true;
    paintMeter(...meter, value);
  } else if (showingParameter) {
    showingParameter = false;
    paintOutputMeter();
  }
  clearTimeout(messageTimer);
  state.message = value;
  render();
  messageTimer = setTimeout(() => {
    state.message = "";
    render();
  }, 1200);
}
function pressFxModifier(input) {
  if (recording) return;
  fxModifiers.add(input);
  state.message = "";
  render();
}
function releaseFxModifier(input) {
  if (!fxModifiers.delete(input) || fxModifiers.size) return;
  clearFxHolds();
  render();
}
function holdFx(input, padIndex) {
  if (!state.playing) return;
  state.message = "";
  fxHolds.set(input, padIndex);
  audio.setEffect(padIndex, state.bpm);
  render();
}
function releaseFx(input) {
  if (!fxHolds.delete(input)) return;
  audio.setEffect([...fxHolds.values()].at(-1) ?? null, state.bpm);
  render();
}
function clearFxHolds() {
  fxHolds.clear();
  audio.setEffect(null, state.bpm);
}
function stop() {
  auditionEpoch++;
  for (const timer of editFlashes.values()) clearTimeout(timer);
  editFlashes.clear();
  previousTurn = null;
  fxModifiers.clear();
  clearFxHolds();
  pendingPlay++;
  clearInterval(timer);
  frames = [];
  state.playing = false;
  state.head = -1;
  audio.silence();
  render();
}
function schedule() {
  const now = audio.context.currentTime;
  const step = 60 / state.bpm / 4;
  // Skip missed steps after a stalled UI thread instead of bursting old notes.
  if (nextTime < now) {
    const missed = Math.ceil((now - nextTime) / step);
    nextBeat = (nextBeat + missed) % 16;
    nextTime += missed * step;
  }
  while (nextTime < now + 0.085) {
    patterns[state.pattern].forEach((lane, slot) => {
      if (lane[nextBeat] >= 0) audio.play(slot, lane[nextBeat], nextTime);
    });
    frames.push([nextTime, nextBeat]);
    nextBeat = (nextBeat + 1) % 16;
    nextTime += step;
  }
  let head = state.head;
  while (frames.length && frames[0][0] <= now) head = frames.shift()[1];
  if (state.head !== head) {
    state.head = head;
    render();
  }
}
async function play() {
  if (state.playing) {
    stop();
    return;
  }
  const start = ++pendingPlay;
  await audio.unlock();
  if (pendingPlay !== start) return;
  state.playing = true;
  nextBeat = 0;
  nextTime = audio.context.currentTime + 0.025;
  schedule();
  startOutputMeter();
  timer = setInterval(schedule, 20);
  render();
}
function finishRecord(cancel = false) {
  const rec = recording;
  if (!rec) return;
  clearTimeout(rec.limitTimer);
  if (cancel && rec.encoder?.state === "recording") rec.encoder.stop();
  if (cancel || !rec.encoder) {
    recording = null;
    rec.stream?.getTracks().forEach((t) => t.stop());
    render();
    return;
  }
  if (rec.encoder.state === "recording") {
    rec.status = "SAVING";
    rec.encoder.stop();
    rec.stream.getTracks().forEach((t) => t.stop());
    render();
  }
}
async function sample(slot) {
  const budget = Math.min(8, audio.remaining(slot));
  if (budget < 0.05) {
    message("MEMORY FULL");
    return;
  }
  const rec = { slot, status: "ALLOW MIC" };
  recording = rec;
  render();
  try {
    await audio.unlock();
    if (recording !== rec) return;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });
    if (recording !== rec) {
      stream.getTracks().forEach((t) => t.stop());
      return;
    }
    rec.stream = stream;
    rec.encoder = new MediaRecorder(stream);
    const chunks = [];
    rec.encoder.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    rec.encoder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      clearTimeout(rec.limitTimer);
      if (recording !== rec) return;
      try {
        const data = await new Blob(chunks, {
          type: rec.encoder.mimeType,
        }).arrayBuffer();
        const raw = await audio.context.decodeAudioData(data);
        if (recording !== rec) return;
        const count = Math.min(raw.length, Math.floor(raw.sampleRate * budget));
        const mono = audio.context.createBuffer(1, count, raw.sampleRate);
        mono.copyToChannel(raw.getChannelData(0).subarray(0, count), 0);
        audio.samples.set(slot, mono);
        recording = null;
        state.slot = slot;
        state.note = 0;
        message("SAMPLE SAVED");
      } catch {
        if (recording === rec) {
          recording = null;
          message("TAKE TOO SHORT");
        }
      }
    };
    rec.encoder.onerror = () => {
      if (recording === rec) {
        finishRecord(true);
        message("MIC ERROR");
      }
    };
    rec.encoder.start();
    rec.status = "RECORDING";
    const deadline = performance.now() + budget * 1000;
    function tick() {
      if (recording !== rec || rec.encoder.state !== "recording") return;
      const remaining = deadline - performance.now();
      if (remaining <= 0) {
        finishRecord();
        return;
      }
      rec.secondsLeft = Math.ceil(remaining / 1000);
      render();
      rec.limitTimer = setTimeout(
        tick,
        remaining - (rec.secondsLeft - 1) * 1000,
      );
    }
    tick();
  } catch {
    if (recording === rec) {
      finishRecord(true);
      message("MIC UNAVAILABLE");
    }
  }
}
function audition(slot, note) {
  const epoch = auditionEpoch;
  audio
    .unlock()
    .then(() => {
      if (epoch !== auditionEpoch) return;
      audio.play(slot, note);
      updatePadLights();
      startOutputMeter();
    })
    .catch(() => message("AUDIO UNAVAILABLE"));
}
function pad(i) {
  previousTurn = null;
  if (recording || fxModifiers.size > 0) return;
  const mode = state.mode;
  if (["sound", "pattern", "record"].includes(mode)) {
    state.mode = "";
    state.message = "";
    if (mode === "record") {
      sample(i);
      return;
    }
    if (mode === "sound") {
      state.slot = i;
      state.note = 0;
      if (!state.playing) audition(i, 0);
    } else state.pattern = i;
  } else if (state.write) {
    const lane = patterns[state.pattern][state.slot];
    lane[i] = lane[i] === -1 ? state.note : -1;
    if (!state.playing && lane[i] >= 0) audition(state.slot, lane[i]);
  } else {
    state.note = i;
    if (!mode) message(noteName(state.slot, i));
    audition(state.slot, i);
  }
  comicOffset = (comicOffset + 1 + (i % 3)) % comicFrames.length;
  if (state.write || mode === "sound" || mode === "pattern") {
    clearTimeout(editFlashes.get(i));
    editFlashes.set(
      i,
      setTimeout(() => {
        editFlashes.delete(i);
        updatePadLights();
      }, 130),
    );
  }
  render();
}
// The K0 emits a fresh bracket keydown for each encoder detent.
let previousTurn = null;
function turnEncoder(direction, time) {
  const interval =
    previousTurn?.direction === direction ? time - previousTurn.time : Infinity;
  previousTurn = { direction, time };
  let steps = 1;
  if (interval >= 0 && interval <= 45) steps = 4;
  else if (interval >= 0 && interval <= 100) steps = 2;
  adjust(direction * steps, direction);
}
// A turn supplies detents. A press restores the active parameter.
function adjust(delta = null, detents = delta) {
  encoderAngles[state.dial] =
    detents === null ? 0 : (encoderAngles[state.dial] + detents * 15) % 360;
  const slot = state.slot;
  if (state.mode === "bpm" && state.dial === "a") {
    state.bpm = delta === null ? DEFAULT_BPM : clip(state.bpm + delta, 60, 240);
    message(state.bpm + " BPM", ["Tempo", state.bpm, 60, 240]);
  } else if (state.dial === "a") {
    const pad = state.note;
    const pitch =
      delta === null
        ? DEFAULT_PITCH
        : clip(audio.pitch[slot][pad] + delta, -12, 12);
    audio.tunePad(slot, pad, pitch);
    message("PAD " + fmt(pad + 1) + " · " + pitch + " ST", [
      "Pitch",
      pitch,
      -12,
      12,
    ]);
  } else {
    audio.level[slot] =
      delta === null
        ? DEFAULT_LEVEL
        : clip(audio.level[slot] + delta * 5, 0, 100);
    message("VOLUME " + audio.level[slot] + "%", [
      "Volume",
      audio.level[slot],
      0,
      100,
    ]);
  }
}
function act(a) {
  previousTurn = null;
  state.message = "";
  if (recording) {
    if (a === "record") finishRecord();
    return;
  }
  if (a === "resetDial") {
    adjust();
    return;
  }
  if (a === "play") {
    play().catch(() => message("AUDIO UNAVAILABLE"));
    return;
  }
  if (a === "write") {
    state.mode = "";
    state.write = !state.write;
  } else if (a === "switch") state.dial = state.dial === "a" ? "b" : "a";
  else if (a === "a" || a === "b") state.dial = a;
  else {
    state.mode = state.mode === a ? "" : a;
    if (state.mode === "bpm") state.dial = "a";
  }
  render();
}
const fxButton = getButton("fx");
fxButton.addEventListener("pointerdown", (e) => {
  if (e.button !== 0) return;
  fxButton.setPointerCapture(e.pointerId);
  pressFxModifier(e.pointerId);
});
for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) {
  fxButton.addEventListener(event, (e) => releaseFxModifier(e.pointerId));
}
for (const button of gear) {
  if (button !== fxButton)
    button.addEventListener("click", () => act(button.dataset.action));
}
for (const b of gear.filter((b) => b.classList.contains("dial"))) {
  let lastY = null;
  b.addEventListener("pointerdown", (e) => {
    act(b.dataset.action);
    lastY = e.clientY;
    b.setPointerCapture(e.pointerId);
  });
  b.addEventListener("pointermove", (e) => {
    if (lastY === null) return;
    const delta = Math.trunc((lastY - e.clientY) / 6);
    if (delta) {
      lastY -= delta * 6;
      adjust(delta);
    }
  });
  b.addEventListener("lostpointercapture", () => {
    lastY = null;
  });
  b.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      act(b.dataset.action);
      adjust(-Math.sign(e.deltaY));
    },
    { passive: false },
  );
}
const actions = {
  KeyT: "sound",
  KeyY: "pattern",
  KeyU: "bpm",
  KeyI: "record",
  KeyO: "switch",
  NumpadDecimal: "resetDial",
  Period: "resetDial",
  NumpadSubtract: "fx",
  Minus: "fx",
  NumpadAdd: "play",
  Space: "play",
  NumpadEnter: "write",
  Enter: "write",
};
// Key travel follows the player's fingers; LEDs follow voices and mode state.
const heldSwitches = new Map();
function holdSwitch(code, button) {
  if (!button?.querySelector(".switch")) return;
  heldSwitches.set(code, button);
  button.classList.add("key-held");
}
function releaseSwitch(code) {
  const button = heldSwitches.get(code);
  if (!button) return;
  heldSwitches.delete(code);
  if (![...heldSwitches.values()].includes(button))
    button.classList.remove("key-held");
}
function releaseAllSwitches() {
  for (const button of heldSwitches.values())
    button.classList.remove("key-held");
  heldSwitches.clear();
}
function resetSession() {
  pauseSession();
  location.reload();
}
$("#reset-session").addEventListener("click", resetSession);
window.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if ($("#help").open) return;
  if (e.code === "Numpad0") {
    e.preventDefault();
    if (!e.repeat) resetSession();
    return;
  }
  if (
    (e.code === "Enter" || e.code === "Space") &&
    e.target.matches("button:focus-visible")
  ) {
    if (!e.repeat) holdSwitch(e.code, e.target);
    if (e.target === fxButton) {
      e.preventDefault();
      if (!e.repeat) pressFxModifier(e.code);
    } else if (fxModifiers.size > 0 && e.target.matches(".pad")) {
      e.preventDefault();
      if (!e.repeat) holdFx(e.code, padButtons.indexOf(e.target));
    }
    return;
  }
  const idx = Math.max(physical.indexOf(e.code), laptop.indexOf(e.code));
  const a = actions[e.code];
  if (
    idx < 0 &&
    !a &&
    !["BracketLeft", "BracketRight", "Escape"].includes(e.code)
  )
    return;
  e.preventDefault();
  if (e.repeat) return;
  holdSwitch(e.code, idx >= 0 ? padButtons[idx] : getButton(a));
  if (idx >= 0 && fxModifiers.size > 0) holdFx(e.code, idx);
  else if (idx >= 0) pad(idx);
  else if (a === "fx") pressFxModifier(e.code);
  else if (a) act(a);
  else if (e.code.startsWith("Bracket"))
    turnEncoder(e.code === "BracketLeft" ? -1 : 1, e.timeStamp);
  else {
    finishRecord(true);
    state.mode = "";
    stop();
  }
});
window.addEventListener("keyup", (e) => {
  releaseSwitch(e.code);
  releaseFxModifier(e.code);
  releaseFx(e.code);
});
function pauseSession() {
  releaseAllSwitches();
  finishRecord(true);
  state.mode = "";
  stop();
}
window.addEventListener("blur", () => {
  // The browser's microphone permission bubble may take focus from the page.
  if (recording?.status === "ALLOW MIC") {
    releaseAllSwitches();
    stop();
    return;
  }
  pauseSession();
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) pauseSession();
});
window.addEventListener("pagehide", pauseSession);
$("#guide").addEventListener("click", () => {
  pauseSession();
  $("#help").showModal();
});
reducedMotion.addEventListener("change", drawDisplay);
render();
