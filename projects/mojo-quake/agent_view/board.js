const el = id => document.getElementById(id);
let live, selected = null, frameKey = "", listKey = "", bestRtt = Infinity, clockOffset;
let atlas, mapKey = "";
const words = value => value ? value[0].toUpperCase() + value.slice(1).replaceAll("_", " ") : "Waiting";
let commandError = "", pending = false, lastFrameFailed = false;
const rowNodes = new Map();
async function syncClock() {
  try {
    const start = performance.now();
    const server = await (await fetch("/api/clock")).json();
    const end = performance.now();
    if (end - start < bestRtt) {
      bestRtt = end - start;
      clockOffset = server - (start + end) / 2;
    }
  } catch {}
}
async function command(op) {
  if (pending) return;
  pending = true;
  commandError = "";
  if (live) render();
  try {
    const response = await fetch("/api/" + op, {method: "POST"});
    if (!response.ok) throw Error(String(response.status));
  } catch {
    commandError = "The board did not accept the command. Check the connection and try again.";
  } finally {
    pending = false;
    if (live) render();
  }
}
el("play").onclick = () => command(live?.requested === "play" ? "pause" : "play");
el("step").onclick = () => command("step");
el("close").onclick = () => command("close");
el("connect").onclick = () => command("connect");
el("encounter").onclick = () => command("encounter");
el("follow").onclick = () => {
  selected = null; render();
  el("display-title").focus({preventScroll: true});
};
el("map-mode").onchange = () => renderMap(live);
function svgNode(tag, attrs, label) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k,v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (label) {
    const title = document.createElementNS(n.namespaceURI,"title");
    title.textContent = label; n.append(title);
  }
  return n;
}
function renderMap(s) {
  if (!s || !atlas) return;
  const routeMode = el("map-mode").value === "route";
  const hint = s.route, map = s.exploration || {}, nav = map.guidance || {};
  const svg = el("map");
  const width = Math.max(180, svg.clientWidth), height = Math.max(120,svg.clientHeight);
  const key = JSON.stringify([width,height,s.generation, routeMode, hint?.source_tick, s.matched_trail, map.total, map.current, map.heading, map.failed_sectors, nav.last_outcome, nav.unsuccessful]);
  if (key === mapKey) return;
  mapKey = key;
  svg.replaceChildren(); svg.setAttribute("viewBox", "0 0 "+width+" "+height);
  svg.setAttribute("aria-label",routeMode ? "Demonstrated E1M1 path and visually matched route samples" : "Estimated connections between visited camera views");
  const points = routeMode ? atlas.points.map(([x,y,tick])=>[tick,y,-x]) :
    (map.places || []).map(([id,x,y])=>[id,-y,x]);
  if (!points.length) return;
  const xs = points.map(p=>p[1]), ys = points.map(p=>p[2]);
  const xmin=Math.min(...xs), xmax=Math.max(...xs), ymin=Math.min(...ys), ymax=Math.max(...ys);
  const scale = Math.min((width-62)/Math.max(2,xmax-xmin),(height-32)/Math.max(2,ymax-ymin));
  const coords = new Map(points.map(([id,x,y])=>[id,[width/2+(x-(xmin+xmax)/2)*scale,height/2+(y-(ymin+ymax)/2)*scale]]));
  const line = (a,b) => svg.append(svgNode("line",{x1:a[0],y1:a[1],x2:b[0],y2:b[1],class:"visited-line","stroke-width":1.5}));
  const dot = (p,r,cls,label) => svg.append(svgNode("circle",{cx:p[0],cy:p[1],r,class:cls},label));
  if (routeMode) {
    svg.append(svgNode("polyline",{points:[...coords.values()].map(p=>p.join(",")).join(" "),fill:"none",class:"route-line","stroke-width":1.5}));
    for (const [end,name] of atlas.stages) {
      const anchor = atlas.points.find(p=>p[2]>=end) || atlas.points.at(-1);
      dot(coords.get(anchor[2]),2.6,"waypoint",name);
    }
    for (const id of new Set(s.matched_trail || [])) if (coords.has(id)) dot(coords.get(id),2.7,"visited-point","Camera matched this part of the route");
    for (const [sample, name] of [[atlas.points[0],"Entrance"], [atlas.points.at(-1),"Exit"]]) {
      const [x,y] = coords.get(sample[2]);
      const label = svgNode("text",{x:Math.min(width-52,x+8),y:Math.max(13,y-8),class:"map-end"});
      label.textContent = name; svg.append(label);
    }
  } else {
    for (const [a,b] of map.links) if(coords.has(a)&&coords.has(b))line(coords.get(a),coords.get(b));
    for (const [id,p] of coords) dot(p,3,"visited-point","Place P"+id);
  }
  const here = routeMode ? (s.matched_trail?.length ? coords.get(hint?.reference_tick) : null) : coords.get(map.current);
  if (here) {
    const matched = !routeMode || hint?.matched;
    svg.append(svgNode("circle",{cx:here[0],cy:here[1],r:5.5,class:matched?"map-marker":"map-marker lost","stroke-width":2},matched?"Current estimate":"Last confirmed match"));
    if (matched && routeMode && s.yaw != null) {
      const a=s.yaw*Math.PI/180;
      svg.append(svgNode("line",{x1:here[0],y1:here[1],x2:here[0]+12*Math.sin(a),y2:here[1]-12*Math.cos(a),class:"map-heading","stroke-width":2}));
    }
  }
  el("landmark").textContent = routeMode ? (hint ? hint.stage+" / "+hint.total+" · "+hint.name : "Finding the entrance") : "Place P"+map.current+" · "+map.total+" estimated places";
  el("map-status").textContent = routeMode ? (hint?.matched?"Camera matched":"Searching for a match")+(hint ? " at tick "+hint.source_tick : "") : "Camera-based estimate · spacing is approximate";
  el("trail-label").textContent = routeMode ? "Confirmed views" : "Visited places";
  el("position-label").textContent = routeMode && !hint?.matched ? "Last matched view" : "Estimated position";
  el("direction").textContent = routeMode ? ((hint?.objective || "") + (hint?.search_turn ? " Looking " + (hint.search_turn === "turn_left" ? "left" : "right") + " for the next landmark." : "")) : nav.last_outcome;
  el("movement").textContent = nav.unsuccessful?.length ? "Failed here · "+nav.unsuccessful.join(" · ") :
    routeMode ? nav.last_outcome : "Untried · "+(nav.untried || []).join(", ");
}
function displayFrame(s, ready, running) {
  const step = selected;
  const historical = Boolean(step);
  const src = historical ? "/api/frame/" + s.generation + "/" + step.id :
    s.picture ? "data:image/jpeg;base64," + s.picture : "";
  const key = [s.generation, historical ? "step" : "board", historical ? step.id : s.tick].join("/");
  el("display-title").textContent = historical ? "Source frame" : "Board display";
  el("display-state").textContent = historical ? "Step " + step.id :
    !s.connected && s.picture ? "Last frame" : s.terminal || (running ? "Live" : ready ? "Paused" : "Offline");
  el("display-state").dataset.state = !historical && running ? "live" : "";
  const tick = historical ? step.source_tick : s.tick;
  el("tick").textContent = tick == null ? "" : "Tick " + tick;
  el("follow").hidden = !historical;
  if (key !== frameKey) {
    frameKey = key;
    lastFrameFailed = false;
    const view = el("view");
    el("age").textContent = "";
    view.onload = () => requestAnimationFrame(() => {
      if (frameKey !== key || historical || !running || !live.connected || live.mode === "paused") return;
      const age = performance.now() + clockOffset - s.capture_mac_ms;
      if (s.capture_mac_ms != null && Number.isFinite(age))
        el("age").textContent = "Preview ≈ " + Math.max(0, Math.round(age)) + " ms";
    });
    view.onerror = () => {
      if (frameKey !== key) return;
      lastFrameFailed = true; view.hidden = true;
      el("empty").hidden = false;
      el("empty").textContent = historical ? "Source frame unavailable." : "Waiting for a new board frame.";
    };
    if (src) view.src = src;
    else view.removeAttribute("src");
  }
  el("view").alt = historical ? "Quake image observed for decision " + step.id : "Rendered Quake frame from the UNO Q";
  el("view").hidden = !src || lastFrameFailed;
  el("empty").hidden = Boolean(src) && !lastFrameFailed;
  if (!src) el("empty").textContent = s.connected ? "Waiting for the first board frame." : "Open the board game to see its display.";
  if (!running || historical) el("age").textContent = "";
  el("board-stats").hidden = historical || !s.picture;
  const stats = s.stats || {};
  el("health").textContent = stats.hp == null ? "—" : Math.max(0,Number(stats.hp));
  el("kills").textContent = stats.kills ?? "—";
  el("shells").textContent = stats.ammo ? stats.ammo.split(",")[0] : "—";
  el("performance").hidden = historical || !ready || s.hz == null;
  if (!el("performance").hidden) el("timing").textContent =
    s.hz.toFixed(1) + " ticks/s · " + s.display_fps.toFixed(0) + " board FPS · " + (s.preview_fps ?? 0).toFixed(0) + " preview FPS";
}

function renderHistory(s) {
  const items = s.history;
  const key = [s.generation,items[0]?.id ?? 0,items.length,selected?.id ?? 0].join(":");
  if (key === listKey) return;
  listKey = key;
  const ids = new Set(items.map(row=>row.id));
  for (const [id,button] of rowNodes) {
    if (!ids.has(id)) { button.remove(); rowNodes.delete(id); }
  }
  const list = el("rows");
  // Insert new receipts at the top without replacing a row the operator is reading.
  let next = list.firstChild;
  for (const row of items) {
    let button = rowNodes.get(row.id);
    if (!button) {
      button = document.createElement("button");
      button.className = "row";
      for (const [cls,value] of [["num","#"+row.id],["scene",row.scene || row.status],
           ["action",words(row.action)],["lat",row.status === "applied" ? row.age_ms+" ms" : words(row.status)]]) {
        const part = document.createElement("span");
        part.className = "row-"+cls; part.textContent = value; button.append(part);
      }
      const result = row.status === "applied" ? "Applied in " + row.age_ms + " milliseconds." : words(row.status) + ".";
      button.setAttribute("aria-label", "Inspect board decision " + row.id + ", " + words(row.action) + ". " + result + " " + (row.scene || ""));
      button.onclick = () => {
        selected = row; render();
        el("follow").focus({preventScroll:true});
        el("display-title").scrollIntoView({block:"start"});
      };
      rowNodes.set(row.id,button);
    }
    button.setAttribute("aria-pressed",String(selected?.id === row.id));
    if (button !== next) list.insertBefore(button,next);
    next = button.nextSibling;
  }
  el("no-history").hidden = !!items.length;
}

function updateActivityScroll(field) {
  if (field.scrollHeight > field.clientHeight) field.tabIndex = 0;
  else field.removeAttribute("tabindex");
}

function setActivityText(id, value) {
  const field = el(id);
  if (field.textContent === value) return;
  field.textContent = value;
  field.scrollTop = 0;
  updateActivityScroll(field);
}

function render() {
  const s = live;
  const ready = Boolean(s.connected && s.board && s.picture);
  const running = ready && (s.mode === "play" || s.mode === "step");
  const closing = s.requested === "closed";
  el("light").dataset.state = ready ? "connected" : "";
  el("connection").textContent = ready ? s.board.board + " · DSI" : "UNO Q · " + (s.phase || "Offline");
  el("play").hidden = el("step").hidden = el("close").hidden = !s.connected;
  el("connect").hidden = el("encounter").hidden = s.connected;
  el("play-label").textContent = s.requested === "play" ? "Pause" : "Play";
  el("play-icon").setAttribute("href",s.requested === "play" ? "#i-pause" : "#i-play");
  el("play").disabled = pending || !ready || closing || !!s.terminal || s.requested === "step";
  el("step").disabled = pending || !ready || closing || !!s.terminal || s.requested !== "paused" || s.mode !== "paused";
  el("close").disabled = pending || !s.connected || closing;
  el("connect").disabled = el("encounter").disabled = pending;
  const error = commandError || s.error;
  el("error").hidden = !error;
  if (el("error").textContent !== (error || "")) el("error").textContent = error || "";
  displayFrame(s,ready,running);
  const step = selected || s.current || s.last;
  el("decision-title").textContent = selected ? "Decision #" + selected.id : step && !s.current ? "Last decision" : "Decision";
  const phase = selected ? "History" : s.terminal || (!s.connected && step ? words(step.status) : s.phase);
  if (el("phase").textContent !== phase) {
    el("phase").textContent = phase;
    el("phase").title = phase;
  }
  const pastWithoutInput = step && (selected || !s.current) && !step.action;
  el("action").textContent = pastWithoutInput ? "No input applied" : words(step?.action);
  el("action").dataset.applied = String(step?.applied_tick != null);
  setActivityText("scene", step?.scene || step?.objective || (ready ? "Single step asks Gemma for one move from the current frame." : "Decisions appear when the game runs."));
  el("api").textContent = step?.api_ms != null ? step.api_ms+" ms" : "";
  el("receipt").hidden = !step;
  el("observed").textContent = step?.source_tick ?? "—";
  el("applied").textContent = step?.applied_tick ?? "—";
  el("input-age").textContent = step?.age_ms != null ? step.age_ms+" ms" : "—";
  const context = [step?.navigation?.prepared_route?.name, step?.opponent ? "Opponent · "+words(step.opponent) : "",
    step?.encounter_reason, step?.camera_reason, step?.shot_outcome,
    step?.turn_ticks ? "Camera turn · " + Math.abs(step.turn_degrees).toFixed(1) + "° " + (step.turn_degrees > 0 ? "left" : "right") + " · " + step.turn_ticks + " ticks" : "",
    step?.end_state ? "Final yaw "+parseFloat(step.end_state.yaw).toFixed(1)+"°" : "", step && step.status !== "applied" ? words(step.status) : ""].filter(Boolean).join("  ·  ");
  setActivityText("step-context", context);
  el("source").hidden = !step;
  if (step) el("source").href = "/api/frame/" + s.generation + "/" + step.id;
  setActivityText("objective", s.plan?.objective || "Waiting for play.");
  setActivityText("evidence", s.plan?.evidence || "");
  el("plan-tick").textContent = s.plan ? "Latest · tick " + s.plan.source_tick : "";
  renderMap(s); renderHistory(s);
}
async function poll() {
  for (;;) {
    try {
      const r = await fetch("/api/live?after="+(live?.revision ?? -1));
      if (!r.ok) throw Error("status");
      const s=await r.json();
      if (!atlas) {
        const mapResponse = await fetch("/api/route");
        if (mapResponse.ok) atlas = await mapResponse.json();
      }
      if (s.generation !== live?.generation) {
        selected = null; listKey = ""; mapKey = ""; frameKey = ""; rowNodes.clear(); el("rows").replaceChildren();
      }
      live=s;render();
    } catch {
      el("connection").textContent="Reconnecting to the Mac"; el("light").dataset.state="";
      for (const id of ["play","step","close","connect","encounter"]) el(id).disabled=true;
      await new Promise(resolve=>setTimeout(resolve,800));
    }
  }
}
new ResizeObserver(() => renderMap(live)).observe(el("map"));
const activityFields = document.querySelectorAll(".activity-text");
const activityResize = new ResizeObserver(entries => {
  for (const {target} of entries) updateActivityScroll(target);
});
for (const field of activityFields) activityResize.observe(field);
document.fonts.ready.then(() => activityFields.forEach(updateActivityScroll));
syncClock(); setInterval(syncClock,2000); poll();
