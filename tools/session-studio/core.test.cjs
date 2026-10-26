const { test } = require('node:test');
const assert = require('node:assert/strict');
const C = require('./core.js');

function event(state, type, extra = {}) { return C.reduce(state, { type, turn_id: 'turn-a', ...extra }); }

test('starter design survives a JSON round trip with distinct reserved regions', () => {
  const layout = C.starter();
  assert.deepEqual(C.validate(JSON.parse(JSON.stringify(layout))), layout);
  assert.deepEqual(C.coverage(layout), { reserved: 93, overlap: 0 });
  assert.equal(C.compose(layout, C.freshState(), 0).pixels.length, 104);
});

test('overlapping regions are opaque, including off pixels, and honor layer order', () => {
  const layout = C.starter();
  const bottom = C.region('bottom', 'Bottom', 'session', 0, 0, 2, 2, '#ffffff', 3);
  const top = C.region('top', 'Top', 'session', 0, 0, 1, 1, '#ffffff', 4);
  bottom.clips.ready.frames[0].rows = ['11', '11'];
  top.clips.ready.frames[0].rows = ['0'];
  layout.regions = [top, bottom];
  const frame = C.compose(layout, C.freshState(), 0);
  assert.equal(frame.pixels[0], 0);
  assert.equal(frame.pixels[1], 1);
  assert.equal(frame.pixels[13], 1);
  assert.equal(frame.owners[0], 'top');
  assert.deepEqual(C.coverage(layout), { reserved: 4, overlap: 1 });
  top.enabled = false;
  assert.equal(C.compose(layout, C.freshState(), 0).pixels[0], 1);
});

test('parallel tools and a user wait remain independent of model output', () => {
  let state = event(C.freshState(), 'turn.started');
  state = event(state, 'tool.started', { activity_id: 'one' });
  state = event(state, 'tool.started', { activity_id: 'two' });
  state = event(state, 'model.started', { activity_id: 'model' });
  state = event(state, 'model.output_started', { activity_id: 'model' });
  state = event(state, 'user_wait.started', { activity_id: 'approval', reason: 'approval' });
  state = event(state, 'tool.finished', { activity_id: 'one', outcome: 'completed' });
  assert.deepEqual(Object.keys(state.tools), ['two']);
  assert.deepEqual(C.channelStates(state), { session: 'working', model: 'responding', tools: 'running', attention: 'approval', connection: 'connected' });
  state = event(state, 'tool.finished', { activity_id: 'two', outcome: 'failed' });
  assert.equal(C.channelStates(state).session, 'working');
  assert.equal(C.channelStates(state).tools, 'error');
  state = event(state, 'tool.started', { activity_id: 'retry' });
  assert.equal(C.channelStates(state).tools, 'running');
});

test('turn completion closes activities and old events cannot corrupt a new turn', () => {
  let state = event(C.freshState(), 'turn.started');
  state = event(state, 'tool.started', { activity_id: 'one' });
  state = event(state, 'turn.finished', { outcome: 'cancelled' });
  assert.deepEqual(state.tools, {});
  state = event(state, 'tool.started', { activity_id: 'late' });
  assert.deepEqual(state.tools, {});
  state = event(state, 'turn.started', { turn_id: 'turn-b' });
  state = event(state, 'turn.finished', { outcome: 'failed' });
  assert.equal(state.outcome, null);
  assert.equal(state.turn_id, 'turn-b');
});

test('lost source retains stale information until a replacement snapshot arrives', () => {
  let state = event(C.freshState(), 'turn.started');
  state = event(state, 'tool.started', { activity_id: 'one' });
  state = event(state, 'source.disconnected');
  assert.equal(C.channelStates(state).connection, 'offline');
  assert.equal(C.channelStates(state).tools, 'running');
  assert.deepEqual(event(state, 'tool.finished', { activity_id: 'one' }), state);
  assert.deepEqual(event(state, 'source.reconnected'), state);
  const updated = event(state, 'source.reconnected', { snapshot: C.freshState() });
  assert.equal(updated.connected, true);
  assert.deepEqual(updated.tools, {});
  assert.equal(updated.outcome, null);
});

test('loop and hold-last playback use each frame duration exactly', () => {
  const clip = { playback: 'loop', frames: [{ rows: ['1'], duration_ms: 20 }, { rows: ['0'], duration_ms: 80 }] };
  assert.equal(C.frameAt(clip, 19).index, 0);
  assert.equal(C.frameAt(clip, 20).index, 1);
  assert.equal(C.frameAt(clip, 99).index, 1);
  assert.equal(C.frameAt(clip, 100).index, 0);
  clip.playback = 'once';
  assert.equal(C.frameAt(clip, 10000).index, 1);
});

test('regional timing starts on a channel transition and survives timeline scrubbing', () => {
  const timeline = C.replayTimeline(C.SCENARIOS.work, 4000);
  assert.equal(timeline.entered_at.session, 600);
  assert.equal(timeline.entered_at.tools, 3400); // The second tool does not restart the running clip.
  assert.equal(timeline.entered_at.model, 3300);
  const layout = C.starter();
  const r = layout.regions.find(r => r.channel === 'tools');
  r.clips.running = { playback: 'once', frames: [{ rows: ['1000', '0000', '0000'], duration_ms: 100 }, { rows: ['0100', '0000', '0000'], duration_ms: 100 }] };
  const first = C.compose(layout, timeline.state, { tools: 0 });
  const held = C.compose(layout, timeline.state, { tools: 300 });
  assert.equal(first.pixels[r.y * 13 + r.x], 1);
  assert.equal(first.pixels[r.y * 13 + r.x + 1], 0);
  assert.equal(held.pixels[r.y * 13 + r.x], 0);
  assert.equal(held.pixels[r.y * 13 + r.x + 1], 1);
  assert.deepEqual(C.replayTimeline(C.SCENARIOS.work, 4000), timeline);
});

test('editing a clip can show a chosen frame without changing session facts', () => {
  const layout = C.starter(), state = C.freshState();
  const before = C.clone(state);
  const r = layout.regions[0];
  r.clips.working.frames[1].rows = Array(7).fill('1111111');
  const composed = C.compose(layout, state, 0, { region_id: r.id, state: 'working', frame_index: 1 });
  assert.equal(composed.pixels.slice(0, 7).join(''), '1111111');
  assert.deepEqual(state, before);
});

test('imports reject unsafe dimensions, duplicate identities, unsupported targets, and malformed clips', () => {
  for (const edit of [
    d => { d.regions[0].x = 12; },
    d => { d.regions[0].id = d.regions[1].id; },
    d => { d.regions[0].clips.ready.frames[0].rows[0] = '2222222'; },
    d => { d.regions[0].clips.ready.frames[0].duration_ms = 19; },
    d => { d.regions[0].clips.ready.frames = Array(33).fill({ rows: Array(7).fill('0000000'), duration_ms: 100 }); },
    d => { d.regions[0].clips.working = null; },
    d => { d.regions[0].channel = '__proto__'; },
    d => { d.regions[0].color = 'red;display:none'; },
    d => { d.target.columns = 32; },
  ]) {
    const invalid = C.starter(); edit(invalid); assert.throws(() => C.validate(invalid));
  }
});

test('moving preserves artwork; resizing rebuilds clips with matching dimensions', () => {
  const r = C.starter().regions[0];
  const clips = C.clone(r.clips);
  C.resizeRegion(r, 1, 0, 7, 7);
  assert.deepEqual(r.clips, clips);
  C.resizeRegion(r, 1, 1, 4, 3);
  for (const clip of Object.values(r.clips)) for (const frame of clip.frames) {
    assert.equal(frame.rows.length, 3);
    assert.ok(frame.rows.every(row => row.length === 4));
  }
});

test('all scenario frames validate and complete; source loss never implies success', () => {
  const layout = C.starter();
  for (const scenario of Object.values(C.SCENARIOS)) {
    for (let at = 0; at <= scenario.duration; at += 50) {
      const state = C.replay(scenario, at);
      const frame = C.compose(layout, state, at);
      assert.equal(frame.pixels.length, 104);
      assert.ok(frame.pixels.every(pixel => pixel === 0 || pixel === 1));
    }
    assert.equal(C.replay(scenario, scenario.duration).outcome, 'completed');
  }
  assert.equal(C.replay(C.SCENARIOS.disconnect, 4000).outcome, null);
});

test('exported wire frame uses the controller MSB-first 104-bit encoding', () => {
  const pixels = Array(104).fill(0); pixels[0] = 1; pixels[103] = 1;
  assert.equal(C.toHex(pixels), '80' + '00'.repeat(11) + '01');
  assert.equal(C.toHex(Array(104).fill(1)), 'ff'.repeat(13));
});
