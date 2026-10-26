/* Shared by the browser and Node's built-in test runner. No device access. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SessionStudio = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const WIDTH = 13, HEIGHT = 8;
  const CHANNELS = {
    session: { label: 'Session', states: ['ready', 'working', 'completed', 'failed', 'cancelled'] },
    model: { label: 'Model', states: ['idle', 'waiting', 'responding'] },
    tools: { label: 'Tools', states: ['idle', 'running', 'error'] },
    attention: { label: 'Attention', states: ['quiet', 'input', 'approval'] },
    connection: { label: 'Connection', states: ['connected', 'offline'] },
  };
  const clone = value => JSON.parse(JSON.stringify(value));
  const blank = (w, h) => Array.from({ length: h }, () => '0'.repeat(w));
  function makeClip(channel, state, w, h) {
    const moving = ['working', 'waiting', 'responding', 'running', 'input', 'approval', 'offline'].includes(state);
    const count = moving ? 4 : 1;
    const frames = Array.from({ length: count }, (_, n) => {
      const rows = blank(w, h).map(row => [...row]);
      const put = (x, y) => { if (x >= 0 && x < w && y >= 0 && y < h) rows[y][x] = '1'; };
      const centerX = Math.floor(w / 2), centerY = Math.floor(h / 2);
      if (['idle', 'quiet'].includes(state)) { /* reserved, blank */ }
      else if (state === 'ready') put(centerX, centerY);
      else if (state === 'working') {
        put(Math.max(0, centerX - 2), centerY); put(Math.min(w - 1, centerX + 2), centerY);
        if (n !== 3) { put(Math.max(0, centerX - 2), centerY - 1); put(Math.min(w - 1, centerX + 2), centerY - 1); }
      } else if (state === 'completed') {
        for (let x = 0; x < w; x++) put(x, Math.round((x < w / 3 ? 0.5 + x / w : 1 - x / w) * (h - 1)));
      } else if (['failed', 'error', 'cancelled'].includes(state)) {
        for (let x = 0; x < w; x++) {
          const y = Math.round(x * (h - 1) / Math.max(1, w - 1));
          put(x, y); if (state !== 'cancelled') put(w - x - 1, y);
        }
      } else if (state === 'waiting' || state === 'running') {
        const points = [[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]];
        const p = points[n]; put(...p);
        if (state === 'running') put(centerX, centerY);
      } else if (state === 'responding') {
        for (let x = 0; x < w; x++) put(x, (x + n) % h);
      } else if (state === 'input' || state === 'approval') {
        if (n !== 3) {
          for (let y = 0; y < Math.max(1, h - 2); y++) put(centerX, y);
          put(centerX, h - 1);
          if (state === 'approval' && w > 2) { put(centerX - 1, 0); put(centerX + 1, 0); }
        }
      } else if (state === 'connected') put(0, h - 1);
      else if (state === 'offline' && n % 2 === 0) for (let x = 0; x < w; x += 2) put(x, centerY);
      return { rows: rows.map(row => row.join('')), duration_ms: moving ? 220 : 500 };
    });
    return { playback: 'loop', frames };
  }
  function region(id, name, channel, x, y, width, height, color, layer) {
    return { id, name, channel, x, y, width, height, color, layer, enabled: true,
      clips: Object.fromEntries(CHANNELS[channel].states.map(state => [state, makeClip(channel, state, width, height)])) };
  }
  function starter() {
    return { schema_version: 1, kind: 'agent-session-layout', name: 'Shared signal',
      target: { id: 'unoq-matrix', columns: WIDTH, rows: HEIGHT, pixel_mode: 'binary' },
      regions: [
        region('session', 'Session', 'session', 0, 0, 7, 7, '#6ebaf5', 0),
        region('model', 'Model activity', 'model', 8, 0, 4, 3, '#bb9ff6', 1),
        region('tools', 'Tool activity', 'tools', 8, 4, 4, 3, '#edb36e', 2),
        region('attention', 'Needs you', 'attention', 12, 0, 1, 7, '#ee96b1', 3),
        region('connection', 'Connection', 'connection', 0, 7, 13, 1, '#8acbb4', 4),
      ] };
  }
  function resizeRegion(r, x, y, w, h) {
    const changed = r.width !== w || r.height !== h;
    Object.assign(r, { x, y, width: w, height: h });
    if (changed) r.clips = Object.fromEntries(CHANNELS[r.channel].states.map(state => [state, makeClip(r.channel, state, w, h)]));
  }
  function freshState() {
    return { open: true, connected: true, turn_id: null, outcome: null, models: {}, tools: {}, waits: {}, tool_error: false };
  }
  function reduce(previous, event) {
    const state = clone(previous);
    if (event.type === 'session.opened') return freshState();
    if (event.type === 'session.closed') return { ...freshState(), open: false };
    if (event.type === 'source.disconnected') return { ...state, connected: false };
    if (event.type === 'source.reconnected') {
      if (!event.snapshot) return state;
      return { ...clone(event.snapshot), connected: true };
    }
    if (!state.connected || !state.open) return state;
    if (event.type === 'turn.started') return { ...freshState(), turn_id: event.turn_id || 'turn-1' };
    if (!state.turn_id || event.turn_id !== state.turn_id || state.outcome) return state;
    const id = event.activity_id;
    switch (event.type) {
      case 'model.started': if (id) state.models[id] = 'waiting'; break;
      case 'model.output_started': if (id && state.models[id]) state.models[id] = 'responding'; break;
      case 'model.finished': delete state.models[id]; break;
      case 'tool.started': if (id) { state.tools[id] = true; state.tool_error = false; } break;
      case 'tool.finished':
        if (state.tools[id]) { delete state.tools[id]; state.tool_error = event.outcome === 'failed'; }
        break;
      case 'user_wait.started': if (id) state.waits[id] = event.reason === 'approval' ? 'approval' : 'input'; break;
      case 'user_wait.finished': delete state.waits[id]; break;
      case 'turn.finished':
        if (!['completed', 'failed', 'cancelled'].includes(event.outcome)) break;
        state.outcome = event.outcome; state.models = {}; state.tools = {}; state.waits = {}; state.tool_error = false;
        break;
    }
    return state;
  }
  function channelStates(state) {
    const models = Object.values(state.models), waits = Object.values(state.waits);
    return {
      session: state.outcome || (state.turn_id ? 'working' : 'ready'),
      model: models.includes('responding') ? 'responding' : models.length ? 'waiting' : 'idle',
      tools: Object.keys(state.tools).length ? 'running' : state.tool_error ? 'error' : 'idle',
      attention: waits.includes('approval') ? 'approval' : waits.length ? 'input' : 'quiet',
      connection: state.connected ? 'connected' : 'offline',
    };
  }
  function frameAt(clip, elapsed) {
    const total = clip.frames.reduce((n, f) => n + f.duration_ms, 0);
    let time = clip.playback === 'loop' ? Math.max(0, elapsed) % total : Math.min(Math.max(0, elapsed), total - 1);
    for (let i = 0; i < clip.frames.length; i++) {
      if (time < clip.frames[i].duration_ms) return { frame: clip.frames[i], index: i };
      time -= clip.frames[i].duration_ms;
    }
    return { frame: clip.frames.at(-1), index: clip.frames.length - 1 };
  }
  function compose(layout, state, elapsed, override = null) {
    const pixels = Array(WIDTH * HEIGHT).fill(0), owners = Array(WIDTH * HEIGHT).fill(null);
    if (!state.open && !override) return { pixels, owners };
    const values = channelStates(state);
    [...layout.regions].filter(r => r.enabled).sort((a, b) => a.layer - b.layer).forEach(r => {
      const chosen = override && override.region_id === r.id;
      const key = chosen ? override.state : values[r.channel];
      const clip = r.clips[key];
      const age = typeof elapsed === 'number' ? elapsed : elapsed[r.channel] || 0;
      const frame = chosen && Number.isInteger(override.frame_index)
        ? clip.frames[override.frame_index] : frameAt(clip, chosen && Number.isFinite(override.elapsed_ms) ? override.elapsed_ms : age).frame;
      for (let y = 0; y < r.height; y++) for (let x = 0; x < r.width; x++) {
        const i = (y + r.y) * WIDTH + x + r.x;
        pixels[i] = Number(frame.rows[y][x]); owners[i] = r.id;
      }
    });
    return { pixels, owners };
  }
  function coverage(layout) {
    const counts = Array(WIDTH * HEIGHT).fill(0);
    for (const r of layout.regions.filter(r => r.enabled))
      for (let y = r.y; y < r.y + r.height; y++) for (let x = r.x; x < r.x + r.width; x++) counts[y * WIDTH + x]++;
    return { reserved: counts.filter(n => n > 0).length, overlap: counts.filter(n => n > 1).length };
  }
  function validate(raw) {
    const fail = message => { throw new Error(message); };
    const int = (n, min, max) => Number.isInteger(n) && n >= min && n <= max;
    if (!raw || raw.schema_version !== 1 || raw.kind !== 'agent-session-layout') fail('Choose a version 1 session layout JSON.');
    const t = raw.target;
    if (!t || t.id !== 'unoq-matrix' || t.columns !== WIDTH || t.rows !== HEIGHT || t.pixel_mode !== 'binary') fail('This studio supports the 13 × 8 binary UNO Q matrix.');
    if (!Array.isArray(raw.regions) || raw.regions.length < 1 || raw.regions.length > 12) fail('A layout needs 1–12 regions.');
    const ids = new Set();
    const regions = raw.regions.map(r => {
      if (!r || typeof r.id !== 'string' || !/^[a-zA-Z0-9_-]{1,48}$/.test(r.id) || ids.has(r.id)) fail('Region IDs must be unique letters, numbers, dashes, or underscores.');
      ids.add(r.id);
      if (!Object.hasOwn(CHANNELS, r.channel)) fail('Unknown region channel.');
      if (typeof r.name !== 'string' || !r.name.trim() || r.name.length > 64) fail('Region names need 1–64 characters.');
      if (!int(r.x, 0, WIDTH - 1) || !int(r.y, 0, HEIGHT - 1) || !int(r.width, 1, WIDTH - r.x) || !int(r.height, 1, HEIGHT - r.y)) fail('A region extends outside the matrix.');
      if (!int(r.layer, 0, 99) || typeof r.enabled !== 'boolean' || typeof r.color !== 'string' || !/^#[0-9a-f]{6}$/i.test(r.color)) fail('Invalid region layer, visibility, or guide color.');
      const clips = {};
      for (const state of CHANNELS[r.channel].states) {
        const clip = r.clips && r.clips[state];
        if (!clip || !['loop', 'once'].includes(clip.playback) || !Array.isArray(clip.frames) || !int(clip.frames.length, 1, 32)) fail('Each state needs a clip of 1–32 frames.');
        const frames = clip.frames.map(f => {
          if (!f || !int(f.duration_ms, 20, 60000) || !Array.isArray(f.rows) || f.rows.length !== r.height || f.rows.some(row => typeof row !== 'string' || row.length !== r.width || /[^01]/.test(row))) fail('Frames need matching binary rows and durations of 20–60,000 ms.');
          return { rows: [...f.rows], duration_ms: f.duration_ms };
        });
        clips[state] = { playback: clip.playback, frames };
      }
      return { id: r.id, name: r.name, channel: r.channel, x: r.x, y: r.y, width: r.width, height: r.height, color: r.color, layer: r.layer, enabled: r.enabled, clips };
    });
    return { schema_version: 1, kind: 'agent-session-layout', name: typeof raw.name === 'string' ? raw.name.slice(0, 64) : 'Untitled layout', target: { id: t.id, columns: WIDTH, rows: HEIGHT, pixel_mode: 'binary' }, regions };
  }
  const e = (at, type, extra = {}) => ({ at, type, turn_id: 'turn-demo', ...extra });
  const SCENARIOS = {
    work: { name: 'A working session', duration: 12000, events: [e(0, 'session.opened'), e(600, 'turn.started'), e(1000, 'model.started', { activity_id: 'model-1' }), e(2200, 'model.output_started', { activity_id: 'model-1' }), e(3300, 'model.finished', { activity_id: 'model-1' }), e(3400, 'tool.started', { activity_id: 'tool-1' }), e(3900, 'tool.started', { activity_id: 'tool-2' }), e(5300, 'tool.finished', { activity_id: 'tool-1', outcome: 'completed' }), e(5900, 'model.started', { activity_id: 'model-2' }), e(6800, 'tool.finished', { activity_id: 'tool-2', outcome: 'completed' }), e(7600, 'model.output_started', { activity_id: 'model-2' }), e(9400, 'model.finished', { activity_id: 'model-2' }), e(9600, 'turn.finished', { outcome: 'completed' })] },
    approval: { name: 'Waiting for approval', duration: 12000, events: [e(0, 'session.opened'), e(400, 'turn.started'), e(700, 'model.started', { activity_id: 'model-1' }), e(2000, 'model.finished', { activity_id: 'model-1' }), e(2100, 'user_wait.started', { activity_id: 'wait-1', reason: 'approval' }), e(6500, 'user_wait.finished', { activity_id: 'wait-1' }), e(6700, 'tool.started', { activity_id: 'tool-1' }), e(8400, 'tool.finished', { activity_id: 'tool-1', outcome: 'completed' }), e(8700, 'model.started', { activity_id: 'model-2' }), e(9300, 'model.output_started', { activity_id: 'model-2' }), e(10400, 'model.finished', { activity_id: 'model-2' }), e(10600, 'turn.finished', { outcome: 'completed' })] },
    recovery: { name: 'Tool failure & recovery', duration: 11000, events: [e(0, 'session.opened'), e(400, 'turn.started'), e(800, 'tool.started', { activity_id: 'tool-1' }), e(2600, 'tool.finished', { activity_id: 'tool-1', outcome: 'failed' }), e(3200, 'model.started', { activity_id: 'model-1' }), e(5000, 'model.finished', { activity_id: 'model-1' }), e(5100, 'tool.started', { activity_id: 'tool-2' }), e(7200, 'tool.finished', { activity_id: 'tool-2', outcome: 'completed' }), e(7400, 'model.started', { activity_id: 'model-2' }), e(8100, 'model.output_started', { activity_id: 'model-2' }), e(9300, 'model.finished', { activity_id: 'model-2' }), e(9500, 'turn.finished', { outcome: 'completed' })] },
    disconnect: { name: 'Source lost & recovered', duration: 10000, events: [e(0, 'session.opened'), e(400, 'turn.started'), e(800, 'model.started', { activity_id: 'model-1' }), e(2600, 'source.disconnected'), e(6200, 'source.reconnected', { snapshot: { ...freshState(), turn_id: 'turn-demo', models: { 'model-1': 'responding' } } }), e(8000, 'model.finished', { activity_id: 'model-1' }), e(8200, 'turn.finished', { outcome: 'completed' })] },
  };
  function replay(scenario, time) { return scenario.events.filter(event => event.at <= time).reduce(reduce, freshState()); }
  function replayTimeline(scenario, time) {
    let state = freshState();
    const entered_at = Object.fromEntries(Object.keys(CHANNELS).map(key => [key, 0]));
    for (const event of scenario.events.filter(event => event.at <= time)) {
      const before = channelStates(state); state = reduce(state, event); const after = channelStates(state);
      for (const key of Object.keys(CHANNELS)) if (before[key] !== after[key]) entered_at[key] = event.at;
    }
    return { state, entered_at };
  }
  function toHex(pixels) {
    return Array.from({ length: 13 }, (_, i) => pixels.slice(i * 8, i * 8 + 8).reduce((byte, bit) => (byte << 1) | bit, 0).toString(16).padStart(2, '0')).join('');
  }
  return { WIDTH, HEIGHT, CHANNELS, SCENARIOS, clone, blank, makeClip, region, starter, resizeRegion, freshState, reduce, channelStates, frameAt, compose, coverage, validate, replay, replayTimeline, toHex };
});
