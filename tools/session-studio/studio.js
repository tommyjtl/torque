(function () {
  'use strict';
  const C = window.SessionStudio;
  const $ = id => document.getElementById(id);
  const storageKey = 'unoq-session-studio-v1';
  let layout = C.starter(), restored = false, storageAvailable = true;
  try { const saved = localStorage.getItem(storageKey); if (saved) { layout = C.validate(JSON.parse(saved)); restored = true; } } catch (_) { storageAvailable = false; }
  let selected = layout.regions[0].id, clipState = 'working', frameIndex = 0, mode = 'live';
  let clock = 1800, motion = !matchMedia('(prefers-reduced-motion: reduce)').matches;
  let scenarioKey = 'work', scenarioTime = 1800, scenarioActive = true, scenarioPlaying = false;
  let state = C.replay(C.SCENARIOS.work, scenarioTime);
  let origins = C.replayTimeline(C.SCENARIOS.work, scenarioTime).entered_at, clipOrigin = clock;
  let log = C.SCENARIOS.work.events.filter(e => e.at <= scenarioTime);
  let undo = [], redo = [], serial = 0, drawMode = false, drawStart = null, drawEnd = null, suppressClick = false;
  let painting = false, paintValue = '1', painted = new Set(), toastTimer;
  const matrixCells = [], miniCells = [];
  const title = value => value.replaceAll('_', ' ').replace(/^./, ch => ch.toUpperCase());
  const region = () => layout.regions.find(r => r.id === selected) || layout.regions[0];
  const clip = () => region().clips[clipState];
  function node(tag, className, text) { const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el; }
  function options(select, entries, value) { select.replaceChildren(...entries.map(([key, label]) => { const item = node('option', '', label); item.value = key; return item; })); select.value = value; }
  function toast(message, error = false) { clearTimeout(toastTimer); $('toast').textContent = message; $('toast').classList.toggle('error', error); $('toast').hidden = false; toastTimer = setTimeout(() => { $('toast').hidden = true; }, error ? 6000 : 3200); }
  function save() {
    try { localStorage.setItem(storageKey, JSON.stringify(layout)); storageAvailable = true; } catch (_) { storageAvailable = false; }
    $('save-status').textContent = storageAvailable ? '● Saved in this browser' : 'Browser storage unavailable · export to keep your design';
  }
  function remember() { undo.push(C.clone(layout)); if (undo.length > 40) undo.shift(); redo = []; }
  function change(fn, message) {
    const before = C.clone(layout); remember();
    try { fn(); layout = C.validate(layout); save(); renderAll(); if (message) toast(message); }
    catch (error) { layout = before; undo.pop(); renderAll(); toast(error.message, true); }
  }
  function normalizeSelection() {
    selected = region().id;
    if (!C.CHANNELS[region().channel].states.includes(clipState)) clipState = C.CHANNELS[region().channel].states[0];
    frameIndex = Math.min(frameIndex, clip().frames.length - 1);
  }
  function selectRegion(id) {
    selected = id; clipState = C.channelStates(state)[region().channel]; frameIndex = 0; renderAll();
  }
  function editClip() { mode = 'clip'; motion = false; scenarioPlaying = false; clipOrigin = clock; }
  function renderRegions() {
    $('region-count').textContent = layout.regions.length;
    $('region-list').replaceChildren(...layout.regions.map((r, index) => {
      const button = node('button', `region-item${r.id === selected ? ' selected' : ''}${r.enabled ? '' : ' disabled'}`);
      button.setAttribute('aria-pressed', String(r.id === selected)); button.setAttribute('aria-label', `Select ${r.name} region`);
      const swatch = node('i', 'region-swatch'); swatch.style.background = r.color;
      const text = node('span', 'region-text'); text.append(node('strong', '', r.name), node('span', '', `${r.width} × ${r.height} · ${C.CHANNELS[r.channel].label}`));
      button.append(swatch, text, node('span', 'region-number', String(index + 1).padStart(2, '0')));
      button.onclick = () => selectRegion(r.id); return button;
    }));
    const coverage = C.coverage(layout), allocation = $('allocation-track'); allocation.replaceChildren();
    const composite = C.compose(layout, { ...state, open: true }, clock);
    for (const r of layout.regions.filter(r => r.enabled)) {
      const count = composite.owners.filter(id => id === r.id).length;
      const segment = node('i'); segment.style.width = `${count / 104 * 100}%`; segment.style.background = r.color; allocation.append(segment);
    }
    $('allocation-label').textContent = `${coverage.reserved} / 104 pixels reserved`;
    $('overlap-label').textContent = coverage.overlap ? `${coverage.overlap} overlapping pixels · higher layers cover lower ones` : `${104 - coverage.reserved} unreserved · no overlaps`;
    $('overlap-label').classList.toggle('warning', coverage.overlap > 0);
    $('add-region').disabled = layout.regions.length >= 12;
  }
  function renderGuides() {
    $('region-guides').replaceChildren(...[...layout.regions].filter(r => r.enabled).sort((a, b) => a.layer - b.layer).map(r => {
      const guide = node('div', `region-guide${r.id === selected ? ' selected' : ''}${r.width < 3 || r.height < 2 ? ' narrow' : ''}`);
      Object.assign(guide.style, { left: `${r.x / 13 * 100}%`, top: `${r.y / 8 * 100}%`, width: `${r.width / 13 * 100}%`, height: `${r.height / 8 * 100}%` });
      guide.style.setProperty('--guide', r.color); guide.append(node('span', '', r.name)); return guide;
    }));
  }
  function renderInspector() {
    const r = region(), current = clip();
    $('region-name').value = r.name; $('region-channel').value = r.channel;
    for (const key of ['x', 'y', 'width', 'height', 'layer', 'color']) $(`region-${key}`).value = r[key];
    $('region-enabled').checked = r.enabled;
    $('region-x').max = 13 - r.width; $('region-y').max = 8 - r.height;
    $('region-width').max = 13 - r.x; $('region-height').max = 8 - r.y;
    options($('clip-state'), C.CHANNELS[r.channel].states.map(s => [s, title(s)]), clipState);
    $('clip-count').textContent = `${current.frames.length} / 32 frames`;
    $('paint-caption').textContent = `${r.width} × ${r.height} · frame ${frameIndex + 1}`;
    const pixels = current.frames[frameIndex].rows.join('');
    $('paint-grid').style.gridTemplateColumns = `repeat(${r.width}, minmax(0, 1fr))`;
    $('paint-grid').replaceChildren(...[...pixels].map((value, index) => {
      const button = node('button', `paint-cell${value === '1' ? ' on' : ''}`); button.dataset.index = index;
      button.setAttribute('aria-label', `Paint pixel column ${index % r.width}, row ${Math.floor(index / r.width)}`); button.setAttribute('aria-pressed', String(value === '1'));
      return button;
    }));
    $('frames').replaceChildren(...current.frames.map((_, index) => {
      const button = node('button', `frame-chip${index === frameIndex ? ' selected' : ''}`, String(index + 1).padStart(2, '0'));
      button.setAttribute('aria-label', `Edit frame ${index + 1}`); button.setAttribute('aria-pressed', String(index === frameIndex));
      button.onclick = () => { frameIndex = index; editClip(); renderAll(); }; return button;
    }));
    $('frame-duration').value = current.frames[frameIndex].duration_ms; $('clip-playback').value = current.playback;
    $('add-frame').disabled = $('duplicate-frame').disabled = current.frames.length >= 32;
    $('delete-frame').disabled = current.frames.length <= 1; $('delete-region').disabled = layout.regions.length <= 1;
    $('undo').disabled = !undo.length; $('redo').disabled = !redo.length;
  }
  function renderSignals() {
    const values = C.channelStates(state);
    $('signal-list').replaceChildren(...Object.entries(C.CHANNELS).map(([key, channel]) => {
      const signal = node('div', 'signal'); let value = title(values[key]);
      if (key === 'tools' && values.tools === 'running') value = `${Object.keys(state.tools).length} running`;
      if (key === 'attention' && values.attention === 'quiet') value = 'No waits';
      if (!state.open && key !== 'connection') value = 'Closed';
      signal.append(node('span', '', channel.label), node('strong', '', value)); return signal;
    }));
    $('session-health').textContent = state.connected ? '● Source connected' : '○ Source lost · last state retained';
    $('session-health').classList.toggle('stale', !state.connected);
  }
  function renderLog() {
    $('event-log').replaceChildren(...log.slice(-30).map(event => {
      const entry = node('div', 'log-entry');
      entry.append(node('time', '', `${((event.at || 0) / 1000).toFixed(1)}s`), node('span', '', event.type), node('span', '', event.outcome || event.reason || event.activity_id || ''));
      return entry;
    }));
    $('event-log').scrollTop = $('event-log').scrollHeight;
  }
  function composition() {
    let override = null;
    if (mode === 'clip') override = { region_id: selected, state: clipState, elapsed_ms: clock - clipOrigin, ...(motion ? {} : { frame_index: frameIndex }) };
    const ages = Object.fromEntries(Object.keys(C.CHANNELS).map(key => [key, Math.max(0, clock - origins[key])]));
    return C.compose(layout, state, ages, override);
  }
  function renderStage() {
    const composite = composition();
    for (let i = 0; i < 104; i++) {
      const on = composite.pixels[i] === 1; matrixCells[i].firstChild.classList.toggle('on', on); miniCells[i].classList.toggle('on', on);
      matrixCells[i].setAttribute('aria-pressed', String(on));
    }
    $('mini-matrix').setAttribute('aria-label', `Matrix output preview: ${composite.pixels.filter(Boolean).length} lit pixels${mode === 'clip' ? ', editing clip' : ''}`);
  }
  function renderPlayback() {
    $('time-current').textContent = `${(scenarioTime / 1000).toFixed(1)}s`;
    $('time-total').textContent = `${(C.SCENARIOS[scenarioKey].duration / 1000).toFixed(1)}s`;
    $('timeline').max = C.SCENARIOS[scenarioKey].duration; $('timeline').value = scenarioTime;
    $('play-scenario').textContent = scenarioPlaying ? 'Ⅱ Pause scenario' : '▶ Play scenario';
  }
  function renderAll() {
    normalizeSelection();
    if (mode === 'live') { clipState = C.channelStates(state)[region().channel]; frameIndex = Math.min(frameIndex, clip().frames.length - 1); }
    renderRegions(); renderGuides(); renderInspector(); renderSignals(); renderLog(); renderPlayback(); renderStage();
    $('live-mode').classList.toggle('active', mode === 'live'); $('clip-mode').classList.toggle('active', mode === 'clip');
    $('live-mode').setAttribute('aria-pressed', String(mode === 'live')); $('clip-mode').setAttribute('aria-pressed', String(mode === 'clip'));
    $('preview-label').textContent = mode === 'live' ? 'SIMULATED SESSION' : `CLIP PREVIEW · ${clipState.toUpperCase()}`;
    $('motion-button').textContent = motion ? 'Ⅱ Pause motion' : '▶ Play motion'; $('motion-button').setAttribute('aria-pressed', String(motion));
    $('selected-caption').textContent = `${region().name} · (${region().x}, ${region().y}) · ${region().width} × ${region().height}${region().enabled ? '' : ' · disabled'}`;
    $('region-guides').hidden = !$('guides').checked;
    $('draw-region').classList.toggle('active', drawMode); $('draw-region').setAttribute('aria-pressed', String(drawMode)); $('matrix').classList.toggle('drawing', drawMode);
    $('canvas-help').textContent = drawMode ? 'Drag across pixels to set the selected region’s rectangle.' : 'Select a region to edit its space and animation.';
  }
  function download(name, value) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + '\n'], { type: 'application/json' }));
    const a = node('a'); a.href = url; a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1500);
  }
  function applyEvent(event) {
    const before = C.channelStates(state), entry = { at: Math.round(clock), ...event };
    state = C.reduce(state, entry); const after = C.channelStates(state);
    for (const key of Object.keys(C.CHANNELS)) if (before[key] !== after[key]) origins[key] = clock;
    log.push(entry); if (log.length > 40) log.shift();
  }
  function ensureTurn() {
    if (!state.turn_id || state.outcome) applyEvent({ type: 'turn.started', turn_id: `turn-manual-${++serial}` });
  }
  const MANUAL = [
    ['turn.started', 'Turn started'], ['model.started', 'Model request started'], ['model.output_started', 'Model output started'], ['model.finished', 'Model request finished'],
    ['tool.started', 'Tool started (+1)'], ['tool.finished', 'Tool finished (−1)'], ['tool.failed', 'Tool failed (−1)'],
    ['wait.input', 'User answer requested'], ['wait.approval', 'User approval requested'], ['user_wait.finished', 'User wait resolved'],
    ['turn.completed', 'Turn completed'], ['turn.failed', 'Turn failed'], ['turn.cancelled', 'Turn cancelled'],
    ['source.disconnected', 'Event source lost'], ['source.reconnected', 'Reconnect with ready snapshot'], ['session.closed', 'Session closed'],
  ];
  function fireManual() {
    const type = $('manual-event').value;
    scenarioPlaying = false; scenarioActive = false; mode = 'live';
    if (!state.connected && !type.startsWith('source.')) { toast('Reconnect or reset the session before sending more activity.'); return; }
    if (!state.open && !type.startsWith('source.')) { toast('Reset the session to reopen it.'); return; }
    if (type === 'source.disconnected') applyEvent({ type });
    else if (type === 'source.reconnected') applyEvent({ type, snapshot: C.freshState() });
    else if (type === 'session.closed') applyEvent({ type });
    else {
      if (type === 'turn.started') applyEvent({ type, turn_id: `turn-manual-${++serial}` });
      else {
        ensureTurn(); const turn_id = state.turn_id;
        if (type === 'model.started') applyEvent({ type, turn_id, activity_id: `model-${++serial}` });
        else if (type === 'model.output_started' || type === 'model.finished') {
          let id = Object.keys(state.models)[0];
          if (!id && type === 'model.output_started') { id = `model-${++serial}`; applyEvent({ type: 'model.started', turn_id, activity_id: id }); }
          if (!id) { toast('There is no active model request.'); renderAll(); return; }
          applyEvent({ type, turn_id, activity_id: id });
        } else if (type === 'tool.started') applyEvent({ type, turn_id, activity_id: `tool-${++serial}` });
        else if (type === 'tool.finished' || type === 'tool.failed') {
          const id = Object.keys(state.tools)[0]; if (!id) { toast('Start a tool first.'); renderAll(); return; }
          applyEvent({ type: 'tool.finished', turn_id, activity_id: id, outcome: type === 'tool.failed' ? 'failed' : 'completed' });
        } else if (type.startsWith('wait.')) applyEvent({ type: 'user_wait.started', turn_id, activity_id: `wait-${++serial}`, reason: type.split('.')[1] });
        else if (type === 'user_wait.finished') {
          const id = Object.keys(state.waits)[0]; if (!id) { toast('There is no open user wait.'); renderAll(); return; }
          applyEvent({ type, turn_id, activity_id: id });
        } else if (type.startsWith('turn.')) applyEvent({ type: 'turn.finished', turn_id, outcome: type.split('.')[1] });
      }
    }
    renderAll();
  }
  function setScenario(time) {
    scenarioTime = time; clock = time; const snapshot = C.replayTimeline(C.SCENARIOS[scenarioKey], time); state = snapshot.state; origins = snapshot.entered_at;
    log = C.SCENARIOS[scenarioKey].events.filter(e => e.at <= time); scenarioActive = true; mode = 'live';
  }
  for (let i = 0; i < 13; i++) $('column-ruler').append(node('span', '', i));
  for (let i = 0; i < 104; i++) {
    const button = node('button', 'led-cell'); button.dataset.index = i; button.setAttribute('aria-label', `Matrix column ${i % 13}, row ${Math.floor(i / 13)}`); button.append(node('span', 'led-dot'));
    $('matrix').append(button); matrixCells.push(button); const dot = node('i'); $('mini-matrix').append(dot); miniCells.push(dot);
  }
  options($('region-channel'), Object.entries(C.CHANNELS).map(([id, ch]) => [id, ch.label]), region().channel);
  options($('scenario'), Object.entries(C.SCENARIOS).map(([id, item]) => [id, item.name]), scenarioKey);
  options($('manual-event'), MANUAL, 'tool.started');
  $('live-mode').onclick = () => { mode = 'live'; renderAll(); };
  $('clip-mode').onclick = () => { editClip(); renderAll(); };
  $('guides').onchange = () => { $('region-guides').hidden = !$('guides').checked; };
  $('motion-button').onclick = () => {
    motion = !motion;
    if (!motion) scenarioPlaying = false;
    if (motion && mode === 'clip') clipOrigin = clock - clip().frames.slice(0, frameIndex).reduce((sum, frame) => sum + frame.duration_ms, 0);
    renderAll();
  };
  $('region-name').onchange = event => change(() => { region().name = event.target.value.trim() || region().name; });
  $('region-channel').onchange = event => change(() => {
    const r = region(); r.channel = event.target.value;
    r.clips = Object.fromEntries(C.CHANNELS[r.channel].states.map(s => [s, C.makeClip(r.channel, s, r.width, r.height)]));
    clipState = C.CHANNELS[r.channel].states[0]; frameIndex = 0;
  }, 'Channel changed. Its starter clips are ready to edit.');
  for (const key of ['x', 'y', 'width', 'height']) $(`region-${key}`).onchange = event => {
    const value = Number(event.target.value); if (!event.target.validity.valid || !Number.isInteger(value)) { toast('Choose coordinates inside the matrix.', true); renderAll(); return; }
    change(() => { const r = region(); const bounds = { x: r.x, y: r.y, width: r.width, height: r.height, [key]: value }; C.resizeRegion(r, bounds.x, bounds.y, bounds.width, bounds.height); frameIndex = 0; }, ['width', 'height'].includes(key) ? 'Resized region. Matching starter clips restored; undo keeps your previous design.' : undefined);
  };
  $('region-layer').onchange = event => change(() => { region().layer = Number(event.target.value); });
  $('region-enabled').onchange = event => change(() => { region().enabled = event.target.checked; });
  $('region-color').onchange = event => change(() => { region().color = event.target.value; });
  $('clip-state').onchange = event => { clipState = event.target.value; frameIndex = 0; editClip(); renderAll(); };
  $('frame-duration').onchange = event => change(() => { clip().frames[frameIndex].duration_ms = Number(event.target.value); });
  $('clip-playback').onchange = event => change(() => { clip().playback = event.target.value; });
  $('clear-frame').onclick = () => change(() => { editClip(); clip().frames[frameIndex].rows = C.blank(region().width, region().height); });
  $('add-frame').onclick = () => change(() => { editClip(); clip().frames.splice(frameIndex + 1, 0, { rows: C.blank(region().width, region().height), duration_ms: clip().frames[frameIndex].duration_ms }); frameIndex++; });
  $('duplicate-frame').onclick = () => change(() => { editClip(); clip().frames.splice(frameIndex + 1, 0, C.clone(clip().frames[frameIndex])); frameIndex++; });
  $('delete-frame').onclick = () => change(() => { editClip(); clip().frames.splice(frameIndex, 1); frameIndex = Math.max(0, frameIndex - 1); });
  $('reset-clip').onclick = () => change(() => { const r = region(); r.clips[clipState] = C.makeClip(r.channel, clipState, r.width, r.height); frameIndex = 0; editClip(); }, 'Starter clip restored.');
  $('add-region').onclick = () => change(() => {
    const id = `region-${Date.now().toString(36)}-${++serial}`;
    layout.regions.push(C.region(id, 'New region', 'tools', 0, 0, 3, 3, '#c2b38e', Math.min(99, Math.max(...layout.regions.map(r => r.layer)) + 1)));
    selected = id; clipState = 'running'; frameIndex = 0;
  });
  $('delete-region').onclick = () => change(() => { layout.regions = layout.regions.filter(r => r.id !== selected); selected = layout.regions[0].id; });
  $('undo').onclick = () => { if (!undo.length) return; redo.push(C.clone(layout)); layout = undo.pop(); normalizeSelection(); save(); renderAll(); };
  $('redo').onclick = () => { if (!redo.length) return; undo.push(C.clone(layout)); layout = redo.pop(); normalizeSelection(); save(); renderAll(); };
  $('reset-layout').onclick = () => change(() => { layout = C.starter(); selected = layout.regions[0].id; clipState = 'working'; frameIndex = 0; }, 'Starter layout restored. Undo brings your design back.');
  $('draw-region').onclick = () => { drawMode = !drawMode; renderAll(); };
  function cellAt(event, container) { const item = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-index]'); return item && container.contains(item) ? item : null; }
  function showDraw() {
    const x = Math.min(drawStart.x, drawEnd.x), y = Math.min(drawStart.y, drawEnd.y), w = Math.abs(drawStart.x - drawEnd.x) + 1, h = Math.abs(drawStart.y - drawEnd.y) + 1;
    Object.assign($('draw-guide').style, { left: `${x / 13 * 100}%`, top: `${y / 8 * 100}%`, width: `${w / 13 * 100}%`, height: `${h / 8 * 100}%` }); $('draw-guide').hidden = false;
  }
  $('matrix').addEventListener('pointerdown', event => {
    if (!drawMode || event.button !== 0) return; const cell = event.target.closest('[data-index]'); if (!cell) return;
    const i = Number(cell.dataset.index); drawStart = drawEnd = { x: i % 13, y: Math.floor(i / 13) }; showDraw(); event.preventDefault();
  });
  $('matrix').addEventListener('click', event => {
    if (suppressClick) { suppressClick = false; return; } if (drawMode) return;
    const cell = event.target.closest('[data-index]'); if (!cell) return;
    const r = C.compose(layout, { ...state, open: true }, clock).owners[Number(cell.dataset.index)]; if (r) selectRegion(r);
  });
  function paintCell(cell) {
    const i = Number(cell.dataset.index); if (painted.has(i)) return; painted.add(i);
    const r = region(), y = Math.floor(i / r.width), x = i % r.width;
    const row = [...clip().frames[frameIndex].rows[y]]; row[x] = paintValue; clip().frames[frameIndex].rows[y] = row.join('');
    cell.classList.toggle('on', paintValue === '1'); cell.setAttribute('aria-pressed', String(paintValue === '1')); renderStage();
  }
  $('paint-grid').addEventListener('pointerdown', event => {
    const cell = event.target.closest('[data-index]'); if (!cell || event.button !== 0) return;
    event.preventDefault(); remember(); editClip(); painting = true; painted = new Set(); paintValue = cell.classList.contains('on') ? '0' : '1'; paintCell(cell);
  });
  $('paint-grid').addEventListener('click', event => {
    if (event.detail !== 0) return; const cell = event.target.closest('[data-index]'); if (!cell) return;
    remember(); editClip(); painted = new Set(); paintValue = cell.classList.contains('on') ? '0' : '1'; paintCell(cell); save(); renderAll();
  });
  document.addEventListener('pointermove', event => {
    if (painting) { const cell = cellAt(event, $('paint-grid')); if (cell) paintCell(cell); }
    if (drawStart) { const cell = cellAt(event, $('matrix')); if (cell) { const i = Number(cell.dataset.index); drawEnd = { x: i % 13, y: Math.floor(i / 13) }; showDraw(); } }
  });
  function endPointer(event) {
    if (painting) { painting = false; save(); renderAll(); }
    if (drawStart) {
      const a = drawStart, b = drawEnd; drawStart = drawEnd = null; drawMode = false; suppressClick = true; $('draw-guide').hidden = true;
      change(() => { C.resizeRegion(region(), Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(a.x - b.x) + 1, Math.abs(a.y - b.y) + 1); frameIndex = 0; }, 'Region bounds updated. Resizing restores matching starter clips.');
      setTimeout(() => { suppressClick = false; }, 0);
    }
  }
  document.addEventListener('pointerup', endPointer); document.addEventListener('pointercancel', endPointer);
  window.addEventListener('blur', () => { if (painting) { painting = false; save(); renderAll(); } drawStart = drawEnd = null; $('draw-guide').hidden = true; });
  $('scenario').onchange = event => { scenarioKey = event.target.value; scenarioPlaying = false; setScenario(0); renderAll(); };
  $('play-scenario').onclick = () => {
    if (scenarioPlaying) { scenarioPlaying = false; motion = false; }
    else { if (!scenarioActive || scenarioTime >= C.SCENARIOS[scenarioKey].duration) setScenario(0); scenarioPlaying = true; motion = true; mode = 'live'; }
    renderAll();
  };
  $('timeline').oninput = event => { scenarioPlaying = false; motion = false; setScenario(Number(event.target.value)); renderAll(); };
  $('reset-session').onclick = () => { scenarioPlaying = false; scenarioActive = false; state = C.freshState(); clock = 0; origins = Object.fromEntries(Object.keys(C.CHANNELS).map(key => [key, 0])); scenarioTime = 0; log = [{ at: 0, type: 'session.opened' }]; mode = 'live'; renderAll(); };
  $('fire-event').onclick = fireManual;
  $('export-button').onclick = () => { download('session-layout.json', C.validate(layout)); toast('Layout exported. Regional clips still need composition for MCU playback.'); };
  $('frame-export').onclick = () => {
    const pixels = composition().pixels;
    download('matrix-frame.json', { schema_version: 1, kind: 'unoq-matrix-frame', columns: 13, rows: 8, encoding: 'bitset-hex-msb', hex: C.toHex(pixels), rows: Array.from({ length: 8 }, (_, y) => pixels.slice(y * 13, y * 13 + 13).join('')) });
  };
  $('import-button').onclick = () => $('import-file').click();
  $('import-file').onchange = async event => {
    const file = event.target.files[0]; event.target.value = ''; if (!file) return;
    if (file.size > 1024 * 1024) { toast('Choose a layout smaller than 1 MB.', true); return; }
    try { const imported = C.validate(JSON.parse(await file.text())); change(() => { layout = imported; selected = layout.regions[0].id; frameIndex = 0; }, 'Layout imported.'); } catch (error) { toast(error.message, true); }
  };
  document.addEventListener('keydown', event => {
    if (event.target.closest('input, select, textarea')) return;
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); (event.shiftKey ? $('redo') : $('undo')).click(); }
    if (event.key === 'Escape') { drawMode = false; drawStart = drawEnd = null; $('draw-guide').hidden = true; renderAll(); }
  });
  let previousTime = performance.now(), lastPaint = 0;
  function tick(time) {
    const delta = Math.min(100, time - previousTime); previousTime = time;
    if (motion) clock += delta;
    if (scenarioPlaying) {
      const previousCount = log.length; scenarioTime = Math.min(C.SCENARIOS[scenarioKey].duration, scenarioTime + delta);
      const snapshot = C.replayTimeline(C.SCENARIOS[scenarioKey], scenarioTime); state = snapshot.state; origins = snapshot.entered_at; clock = scenarioTime;
      log = C.SCENARIOS[scenarioKey].events.filter(e => e.at <= scenarioTime);
      if (scenarioTime === C.SCENARIOS[scenarioKey].duration) scenarioPlaying = false;
      if (previousCount !== log.length) { renderSignals(); renderLog(); }
      renderPlayback();
    }
    if (time - lastPaint > 45) { if (!painting) renderStage(); lastPaint = time; }
    requestAnimationFrame(tick);
  }
  renderAll(); save(); requestAnimationFrame(tick);
  if (restored) $('save-status').textContent = '● Previous design restored · saved in this browser';
})();
