const el = (id) => document.getElementById(id);
el("board-live-link").hidden = location.port !== "8790";
let live,
  selected,
  selecting = 0,
  lastRows = "",
  priorImage = "";
const words = (s) =>
  s === "aim_fire" ? "Aim & fire" : s ? s.replaceAll("_", " ") : "Waiting";
const latency = (ms) =>
  ms == null ? "—" : ms < 1000 ? ms + " ms" : (ms / 1000).toFixed(2) + " s";
const layeredName = id => id === "google/gemma-4-31b-it" ? "Modular Cloud · Gemma 4 31B" : "Mac · Laya English 421M";
const actorName = id => id === "google/gemma-4-31b-it" ? "Gemma" : "Laya";
function point(name, vision) {
  if (vision.unlocated?.includes(name)) {
    el(name).textContent = "Location unclear";
    return;
  }
  if (!(name in vision)) {
    el(name).textContent = "—";
    return;
  }
  const value = vision[name];
  el(name).textContent = value
    ? value.map((n) => Math.round(n) + "%").join(", ")
    : "None seen";
}
function pin(type, coords) {
  const node = document.createElement("div"),
    label = document.createElement("span");
  node.className = "pin " + type;
  node.style.left = coords[0] + "%";
  node.style.top = coords[1] + "%";
  label.textContent = type[0].toUpperCase() + type.slice(1);
  node.append(label);
  return node;
}
let planChoice = null, cachedPlan = null, planOptions = "";
const planModel = (id) => ({
  "MiniMaxAI/MiniMax-M3.1-Flash": "MiniMax M3.1 Flash",
  "google/gemma-4-31b-it": "Gemma 4 31B",
  "deepseek/deepseek-v4.1-flash-1017": "DeepSeek V4.1 Flash",
})[id] || id;
const planStatus = (p) => p.status === "Used" && !p.next_input ? "Delivered" : p.status;
function renderPlanner(event) {
  const feed = live.planning;
  const recorded = [event?.plan, event?.planner_request].filter(Boolean);
  const rows = selected ? [...new Map(recorded.map((p) => [p.id, p])).values()] : (feed?.records || []);
  const enabled = selected ? rows.length > 0 : Boolean(feed);
  let plan = rows.find((p) => p.id === planChoice);
  if (!selected && planChoice != null) {
    if (plan) cachedPlan = plan;
    else plan = cachedPlan;
  }
  plan ||= (selected ? event.plan : rows.find((p) => p.id === feed?.active_id)) || rows.at(-1);
  el("strategy").classList.toggle("strategy-idle", !enabled);
  el("plan-provider").textContent = enabled ? (planModel(plan?.model || feed?.model) || "Strategy") : "This run";
  const starting = !selected && !enabled && live.requested_controller==="layered";
  el("plan-state").textContent = plan ? planStatus(plan) : (enabled || starting ? "Standby" : "Off");
  el("plan-state").dataset.status = plan?.status || "";
  el("plan-headline").textContent = plan?.objective || (plan?.status === "Reviewing" ?
    "Reviewing the source frame while the player continues." :
    plan?.status_note || (enabled || starting ? "Waiting for the first observation." :
    selected ? "No background plan was recorded for this step." : live.player_modes ? "Choose Local player + planner to see strategy updates." : "Vision and input decisions run without a background planner."));
  el("plan-details").hidden = !plan;
  if (!plan) return;
  el("plan-evidence").textContent = plan.evidence || plan.trigger;
  el("plan-character").textContent = plan.character ? words(plan.character) : "Awaiting assessment";
  el("plan-success").textContent = plan.success || "Awaiting objective";
  el("plan-recommendation").textContent = plan.next_input ? words(plan.next_input) : "—";
  el("plan-receipt").textContent = plan.applied_step ?
    words(plan.applied_input) + " at step " + plan.applied_step + " · " + plan.input_source :
    plan.status_note || (plan.seen_step ? "Chose " + words(plan.first_input) + " at step " + plan.seen_step :
    plan.status === "Reviewing" ? "Player continues independently" : "Awaiting a local decision");
  const url = "/api/planner-frame/" + live.run + "/" + plan.source_tick;
  if (el("plan-frame-image").getAttribute("src") !== url) {
    el("plan-frame-link").href = url;
    el("plan-frame-image").src = url;
  }
  const mark = plan.marker;
  el("plan-marker").hidden = !mark;
  if (mark) {
    el("plan-marker").style.left = mark.point[0]+"%";
    el("plan-marker").style.top = mark.point[1]+"%";
  }
  el("plan-frame-caption").textContent = "Source frame · tick " + plan.source_tick + (mark ? " · "+words(mark.kind) : "");
  const pending = !selected && rows.at(-1)?.status === "Reviewing" && rows.at(-1)?.id !== plan.id;
  el("plan-timing").textContent = plan.trigger + " · step " + plan.source_step +
    (plan.latency_ms != null ? " · " + latency(plan.latency_ms) : "") +
    (pending ? " · newer frame under review" : "");
  const key = [live.run, selected?.seq, ...rows.map((r) => r.id + r.status), planChoice].join("/");
  if (key !== planOptions) {
    planOptions = key;
    const list = el("plan-list");
    list.replaceChildren(new Option(selected ? "At this step" : "Follow live plan", ""));
    const items = rows.slice().reverse();
    if (!selected && cachedPlan && !rows.some((r) => r.id === cachedPlan.id)) items.push(cachedPlan);
    for (const record of items) list.add(new Option("Step " + record.source_step + " · " + planStatus(record),record.id));
    list.value = planChoice == null ? "" : String(planChoice);
  }
}
el("plan-list").onchange = (event) => {
  planChoice = event.target.value ? Number(event.target.value) : null;
  cachedPlan = null;
  render();
};
let previewKey = "";
function renderPreview(event) {
  const preview = event?.lookahead;
  el("preview-panel").hidden = !preview;
  if (!preview) { previewKey = ""; return; }
  const key = [live.run, preview.batch, preview.status, event.lookahead_interrupted].join("/");
  if (key === previewKey) return;
  previewKey = key;
  const options = preview.alternatives || [];
  el("preview-status").textContent = preview.status;
  el("preview-choice").textContent = options.length
    ? (event.lookahead_interrupted ? "Started " : "Chose ") + preview.selected + " after comparing " + options.length + " moves in " + preview.latency_ms + " ms."
    : preview.reason || "Trying moves in a second game while the live player moves.";
  if (preview.released_camera?.direction === "rising") el("preview-choice").textContent += " The camera rose with movement released.";
  const local = preview.local_choice;
  if (local) el("preview-choice").textContent += " " + actorName(local.model) + " suggested " + local.input + " in " + local.ms + " ms.";
  const frontier = preview.frontier;
  if (frontier?.steps != null) {
    const destination = frontier.purpose === "revisit door" ? "The remembered door is " : "An unvisited passage is ";
    el("preview-choice").textContent += " " + destination + frontier.steps + (frontier.steps === 1 ? " tested move" : " tested moves") + " away.";
  }
  el("preview-details").hidden = !options.length;
  const guide = preview.panorama_plan;
  el("preview-guidance").textContent = guide ? guide.objective + " " + guide.evidence : "";
  el("preview-panorama").hidden = !guide;
  if (guide) el("preview-panorama").href = "/api/panorama-frame/" + live.run + "/" + guide.source_tick;
  const sheet = el("preview-sheet");
  if (preview.sheet_tick != null) sheet.src = "/api/preview-frame/" + live.run + "/" + preview.sheet_tick;
  else sheet.removeAttribute("src");
  el("preview-source").textContent = "Own save at tick " + preview.source_tick + " · live camera matched at tick " + (preview.selected_tick ?? "—");
  if (preview.archive) {
    const graph = preview.archive;
    const outcome = graph.visible_exit ? " · exit screen seen in preview" : "";
    el("preview-source").textContent += " · Private graph · " + graph.trials + " moves from " + graph.own_saves + " own saves" + outcome;
  }
  el("preview-options").replaceChildren(...options.map(o => {
    const row = document.createElement("li");
    row.textContent = o.input + " · score " + o.score + (o.visible_hp != null ? " · HP " + o.visible_hp : "") + (o.game_message ? " · " + o.game_message : "") + (o.interaction ? " · " + o.interaction.notice : "") + (o.verified_return ? " · Return matched the earlier camera views" : "") + (o.backtracking ? " · Leads toward the mapped objective" : "") + (o.ride_observed ? (o.after_step ? " · Tested the ride and step off" : " · Stayed aboard during ascent") : "") + (o.jump_comparison ? (o.jump_comparison.different_landing ? " · Reached a different view from walking" : " · Similar landing to walking") : "");
    return row;
  }));
}
function renderJev(event) {
  const panel = el("jev-inspector");
  panel.hidden = live.controller !== "jev" && event?.controller !== "jev";
  el("jev-mode").hidden = live.controller !== "jev";
  if (panel.hidden) return;
  // Keep the latest evaluated frame visible while the next request is in flight.
  const step = selected || (event?.jev ? event : live.history.slice().reverse().find(r => r.jev)) || event;
  const result = step?.jev;
  const link = el("jev-frame-link");
  link.hidden = step?.jev_frame_tick == null;
  el("jev-step").textContent = link.hidden ? "" : "Step " + step.seq + " · tick " + step.jev_frame_tick;
  if (!link.hidden) {
    const url = "/api/jev-frame/" + live.run + "/" + step.jev_frame_tick;
    if (el("jev-frame").getAttribute("src") !== url) {
      link.href = url;
      el("jev-frame").src = url;
    }
  }
  const box = result?.box;
  const mark = el("jev-box");
  mark.hidden = !box || !el("marks").checked;
  if (!mark.hidden) {
    Object.assign(mark.style, {
      left: box.left * 100 + "%", top: box.top * 100 + "%",
      width: (box.right-box.left) * 100 + "%", height: (box.bottom-box.top) * 100 + "%"
    });
  }
  el("jev-facts").hidden = !result;
  el("jev-what").textContent = result ? "Visual cue · " + words(result.cue) :
    step?.note || (step?.jev_frame_tick != null ? "Reading this frame…" : "Press Single step to see a Jev decision.");
  if (!result) return;
  el("jev-choice").textContent = words(result.proposed) + " · " + Math.round(result.action_confidence*100) + "%";
  el("jev-applied").textContent = step.applied_tick == null ? (step.note || "No input applied") :
    (step.action === "hold" ? "Hold input" : words(step.action)) + " · tick " + step.applied_tick;
  el("jev-target").textContent = words(result.target) + " · " + Math.round(result.target_confidence*100) + "%";
  el("jev-ms").textContent = latency(result.api_ms);
  if (result.preview) el("jev-what").textContent += " · " + result.preview.detail;
}
function renderRouteGuide(event) {
  const guide = selected ? event?.route_guide : (event?.route_guide || live.route_guide);
  el("route-guide").hidden = !guide;
  if (!guide) return;
  el("guide-match").textContent = guide.matched ? "Camera matched" : "Looking for a match";
  el("guide-landmark").textContent = guide.stage + " / " + guide.total + " · " + guide.name;
  el("guide-instruction").textContent = guide.objective;
  el("guide-move").textContent = guide.suggested ? "Suggested input · " + words(guide.suggested) : "Last known route section";
  const photo = "/api/route-photo/" + guide.photo;
  if (el("guide-photo").getAttribute("src") !== photo) el("guide-photo").src = photo;
  if (!el("guide-takeoff").hasAttribute("src")) {
    el("guide-takeoff").src = "/api/route-photo/0";
    el("guide-landing").src = "/api/route-photo/1";
    for (const name of live.route_stages || []) {
      const li = document.createElement("li");
      li.textContent = name;
      el("guide-stages").append(li);
    }
  }
}
function render() {
  if (!live) return;
  const event = selected || live.current,
    vision = event?.vision;
  el("mode-control").hidden = !live.player_modes;
  el("laya-mode").hidden = live.controller !== "layered" || live.player_modes;
  el("laya-mode").textContent = "Player · " + layeredName(live.layered_model);
  el("player-mode").options[1].textContent = actorName(live.layered_model) + " + planner";
  el("player-mode").value = live.requested_controller==="layered" ? "local-planner" : "cloud-player";
  el("player-mode").disabled = live.ended || live.finishing;
  el("gemma-input-control").hidden = !live.gemma_input;
  el("gemma-input").value = live.gemma_input || "gemma-text";
  el("gemma-input").disabled = live.ended || live.finishing || !live.ready;
  const screenshotMode = live.gemma_input === "gemma-screenshots";
  const frameCheck = selected || (event?.gemma_sighting ? event : live.history.slice().reverse().find(row => row.gemma_sighting));
  const receipt = frameCheck?.gemma_sighting;
  const showCheck = selected ? !!selected.gemma_frame_reason : screenshotMode;
  el("gemma-check").hidden = !showCheck;
  if (showCheck) {
    const sight = {live: "Live monster", fallen: "Fallen monster", none: "No monster seen", unclear: "Unclear"};
    el("gemma-check-status").textContent = receipt
      ? "Gemma saw · " + sight[receipt.sighting] + (receipt.region === "unknown" ? "" : " · " + receipt.region)
        + " · step " + frameCheck.seq + " · " + frameCheck.gemma_frame_reason
      : selected ? (selected.note || "No screenshot result recorded") : "Waiting for a game screenshot.";
    const inspectButton = el("inspect-gemma-frame");
    inspectButton.hidden = !!selected || !receipt;
    inspectButton.disabled = !live.history.some(row => row.seq === frameCheck?.seq);
    inspectButton.dataset.step = frameCheck?.seq || "";
  }
  renderPlanner(event);
  renderRouteGuide(event);
  renderPreview(event);
  renderJev(event);
  const data = selected ? selected.frame : live.frame;
  if (data && data !== priorImage) {
    el("view").src = "data:image/jpeg;base64," + data;
    priorImage = data;
  }
  if (!data) {
    el("view").removeAttribute("src");
    priorImage = "";
  }
  el("empty").hidden = !!data;
  el("connection-light").className = "good";
  el("connection").textContent = "Mac connected";
  el("error").hidden = !live.error;
  el("error").textContent = live.error;
  el("phase").textContent = selected ? event.note || "Recorded" : live.phase;
  el("frame-title").textContent = selected ? "Model input" : "Game view";
  let tick = selected ? selected.observed_tick : live.tick;
  el("tick").textContent = "TICK " + tick;
  el("frame-mode").textContent = selected
    ? "Observed for step " + selected.seq
    : live.timing === "real-time"
      ? "Real-time · 72 Hz"
      : "Live frame";
  el("markers").replaceChildren();
  const currentEnemy = !selected && live.screen_enemy?.point;
  el("marks").disabled = !vision && !currentEnemy;
  if (el("marks").checked) {
    if (currentEnemy) el("markers").append(pin("enemy", currentEnemy));
    if (vision && tick === event.observed_tick)
      for (const type of ["enemy", "route", "landing", "switch", "platform", "pickup","panel"])
        if (vision[type] && !(type === "enemy" && currentEnemy))
          el("markers").append(pin(type, vision[type]));
  }
  el("scene").textContent =
    vision?.scene || event?.lookahead?.panorama_plan?.evidence || (event?.input_source === "Own-save lookahead" ? "The live viewpoint matched the camera preview." : "") ||
    (live.phase?.startsWith("Reading frame")
      ? "Reading the game frame…"
      : "Waiting for an observation.");
  for (const type of ["enemy", "route", "landing"]) {
    if (vision) point(type, vision);
    else el(type).textContent = "—";
  }
  el("clearance").textContent = vision?.clearance
    ? words(vision.clearance)
    : "—";
  el("blocker").textContent = vision?.blocker ? words(vision.blocker) : "—";
  const jev = (event?.controller || live.controller) === "jev";
  const combined = jev || (event ? event.controller === "single-call" : live.controller === "single-call");
  const cloudId =
    event?.cloud_model ||
    (selected ? "google/gemma-4-31b-it" : live.vision_model);
  const name =
    {
      "google/gemma-4-31b-it": "Gemma 4 31B",
      "MiniMaxAI/MiniMax-M3.1-Flash": "MiniMax M3.1 Flash",
      "qwen/qwen3.8-27b": "Qwen3.8 27B",
      "deepseek/deepseek-v4.1-flash-1017": "DeepSeek V4.1 Flash",
    }[cloudId] || cloudId;
  const layered = event ? event.controller === "layered" : live.controller === "layered";
  const actorId = event ? event.decision_model : live.decision_model;
  const localCharacter = event?.input_source === "Local character detector";
  el("vision-provider").textContent = event?.checkpoint ? "Native Quake" : jev ? "TypeSafe · Jev 1.14" : localCharacter ? "Mac · " + (event.vision_detector || "YOLO11n") : layered ? "Mac · RGB camera and HUD" : "Modular Cloud · " + name;
  el("decision-provider").textContent = [
    "Local fallback",
    "local recovery",
    "HUD reflex",
    "HUD pickup",
    "Quake checkpoint",
    "Checkpoint memory",
    "Local character detector",
    "Navigation recovery",
    "Camera navigation",
    "Landmark inspection",
    "Own-save lookahead",
    "Game message",
  ].includes(event?.input_source)
    ? event.input_source
    : jev ? "TypeSafe · same call" : layered ? layeredName(actorId) : combined
      ? "Modular Cloud · same call"
      : "Mac · Gemma 4 E4B";
  el("vt").textContent = latency(
    combined && !localCharacter ? event?.inference_ms : event?.vision_ms,
  );
  el("dt").textContent = combined ? "" : latency(event?.decision_ms);
  el("action").textContent =
    event?.note === "Expired"
      ? "Skipped · " + words(event.action)
      : event?.timing === "real-time" && !event.action
        ? "No input"
        : words(event?.action);
  el("reason").textContent =
    (event?.reason &&
      (event.input_source === "HUD reflex"
        ? "HUD · "
        : event.input_source === "local recovery"
          ? "Recovery · "
          : localCharacter ? "Camera · " : "Selected cue · ") + event.reason) ||
    (jev && live.phase === "Jev is reading the scene" ? "Game running while Jev reads the frame…" : combined && live.phase === "Reading frame and choosing input"
      ? "Game running while Gemma reads the frame and chooses an input…"
      : live.phase === "Choosing game input" && layered
        ? "Game running while " + actorName(actorId) + " chooses an input…"
      : live.phase === "Choosing action"
        ? "Game running while the Mac chooses an input…"
        : "Waiting for a decision.");
  if (event?.dodge_tick != null && !selected && live.phase === "Dodging during inference")
    el("action").textContent = "Dodging";
  if (event?.actor_source === "Modular Gemma" && event.input_source !== event.actor_source && event.applied_tick != null) {
    el("decision-provider").textContent = layeredName(actorId);
    el("action").textContent = words(event.actor_choice);
    el("dt").textContent = latency(event.actor_ms);
    el("reason").textContent = "Applied input · " + words(event.action) + " (" + event.input_source + "). " + (event.reason || "");
  }
  if (event?.movement_lesson) {
    const lesson = event.movement_lesson;
    const name = {release_blocked_forward: "Blocked forward", compare_onward_turns: "Compare turns", compare_walk_and_jump: "Compare landings"}[lesson.lesson] || "Movement lesson";
    el("reason").textContent += " · " + name + " · " + lesson.advice;
  }
  const actorMemory = event?.controller === "layered" ? event.navigation : null;
  const lessons = [...(actorMemory?.movement_lesson ? [actorMemory.movement_lesson.advice] : []),
    ...(actorMemory?.past_traversal || [])];
  el("actor-memory").hidden = !lessons.length;
  el("actor-memory").querySelector("summary").textContent = "Experience sent to " + actorName(actorId);
  el("actor-lessons").replaceChildren(...lessons.map(text => {
    const item = document.createElement("li");
    item.textContent = text;
    return item;
  }));
  const lag =
    event?.applied_tick != null ? " · applied tick " + event.applied_tick : "";
  el("input").textContent = event
    ? "Step " +
      event.seq +
      " · observed tick " +
      event.observed_tick +
      lag +
      (event.jump_press_tick ? " · jump tick " + event.jump_press_tick : "") +
      (event.ticks ? " · held " + event.ticks + " ticks" : "") +
      (event.note ? " · " + event.note : "")
    : "";
  if (event?.navigation)
    el("input").textContent +=
      " · " + event.navigation.place + " · visit " + event.navigation.visits;
  if (event?.exploration) {
    const progress = event.exploration;
    el("input").textContent += " · " + progress.state + " · " +
      progress.seconds_since_new_views + " s since new moving views · " + progress.recoveries + " recoveries";
  }
  if(event?.grounded) el("input").textContent += " · Matched " + words(event.grounded.kind) + " in current view";
  if(event?.released_target) el("input").textContent += " · Released unchanged silhouette";
  if(event?.mechanism) el("input").textContent += " · " + event.mechanism.objective;
  if(event?.camera_lanes) el("vision-provider").textContent = localCharacter ? el("vision-provider").textContent : "Mac · RGB scene estimate";
  if(event?.navigation?.prepared_route?.suggested) el("vision-provider").textContent = "Mac · route landmark matched";
  if (event?.checkpoint) el("input").textContent += " · Checkpoint " + event.checkpoint.slot;
  const saves = selected ? event?.checkpoint_context || event?.navigation?.checkpoints : live.checkpoints;
  el("save-status").textContent = saves ? saves.saves + " saves · " + saves.reloads + " reloads" : "Single life";
  if (event?.checkpoint) el("scene").textContent = event.reason;
  const message = event?.navigation?.hud?.game_message;
  el("game-message").hidden = !message;
  el("game-message").textContent = message ? "Game message · " + message : "";
  refreshMap();
  const stats = selected?.observed_stats || live.stats;
  el("health").textContent = stats.hp ?? "—";
  el("kills").textContent = stats.kills ?? "—";
  el("sim").textContent = (tick / 72).toFixed(1) + " s";
  el("live").hidden = !selected;
  el("play").textContent = live.auto ? "Pause" : "Play";
  el("play").disabled = !live.ready || live.ended;
  el("step").disabled = !live.ready || live.busy || live.auto || live.ended;
  el("finish").disabled =
    !live.ready ||
    live.ended ||
    live.finishing ||
    (!live.busy && !live.history.length);
  el("finish").textContent = live.finishing ? "Finishing…" : "Finish & save";
  el("reset").disabled = live.phase === "Starting game";
  el("goal").textContent = live.goal || "";
  const recorded = live.history.at(-1)?.seq || 0;
  el("capture-state").textContent = live.ended
    ? "Run ended · " + recorded + " decisions captured"
    : recorded
      ? "Recording this run · " + recorded + " decisions captured"
      : "Ready to record the first decision";
  el("scenario").value = live.scenario || "entrance";
  el("handoff").textContent =
    live.scenario === "encounter"
      ? "Recorded approach · live control from tick 703"
      : "";
  const key =
    live.run +
    "-" +
    (live.history.at(-1)?.seq || 0) +
    "-" +
    (selected?.seq || 0);
  if (key !== lastRows) {
    lastRows = key;
    const rows = live.history
      .slice()
      .reverse()
      .map((r) => {
        const btn = document.createElement("button");
        btn.className =
          "history-row" + (r.seq === selected?.seq ? " selected" : "");
        btn.setAttribute("aria-label", "Inspect decision " + r.seq);
        for (const [kind, text] of [
          ["num", "#" + String(r.seq).padStart(2, "0")],
          ["scene", r.vision?.scene || r.note || "Awaiting observation"],
          [
            "action",
            r.note === "Expired"
              ? "Skipped"
              : r.action
                ? words(r.action)
                : "No input",
          ],
          [
            "lat",
            latency(
              r.inference_ms ??
                (r.decision_ms == null
                  ? r.vision_ms
                  : (r.vision_ms || 0) + r.decision_ms),
            ),
          ],
        ]) {
          const cell = document.createElement("span");
          cell.className = "row-" + kind;
          cell.textContent = text;
          btn.append(cell);
        }
        btn.onclick = () => inspect(live.run, r.seq);
        return btn;
      });
    if (!rows.length) {
      const p = document.createElement("p");
      p.className = "placeholder";
      p.textContent = "Play or single-step to record the first decision.";
      rows.push(p);
    }
    el("rows").replaceChildren(...rows);
  }
}
async function inspect(run, seq) {
  const ticket = ++selecting;
  const r = await fetch("/api/decision/" + run + "/" + seq);
  if (!r.ok) return;
  const record = await r.json();
  if (ticket === selecting && live.run === run) {
    selected = record;
    planChoice = cachedPlan = null;
    render();
  }
}
function follow() {
  selecting++;
  selected = null;
  planChoice = cachedPlan = null;
  render();
}
async function command(op) {
  follow();
  try {
    const r = await fetch("/api/" + op, { method: "POST" });
    if (!r.ok && r.status !== 409) throw Error("HTTP " + r.status);
  } catch (e) {
    el("connection").textContent = "Control unavailable";
  }
}
el("play").onclick = () => command(live?.auto ? "pause" : "play");
el("step").onclick = () => command("step");
el("finish").onclick = () => command("finish");
el("reset").onclick = () => command("reset");
el("live").onclick = follow;
el("marks").onchange = render;
el("scenario").onchange = (event) => command(event.target.value);
el("player-mode").onchange = (event) => command(event.target.value);
el("gemma-input").onchange = (event) => command(event.target.value);
el("inspect-gemma-frame").onclick = (event) => inspect(live.run, Number(event.currentTarget.dataset.step));
async function poll() {
  for (;;) {
    try {
      const r = await fetch("/api/live?after=" + (live?.revision ?? -1));
      if (r.status === 204) continue;
      if (!r.ok) throw Error();
      const next = await r.json();
      if (live?.run !== next.run) {
        selected = null;
        planChoice = cachedPlan = null;
        selecting++;
      }
      live = next;
      render();
    } catch {
      el("connection").textContent = "Reconnecting";
      el("connection-light").className = "";
      await new Promise((r) => setTimeout(r, 900));
    }
  }
}
let mapKey = "";
function svg(tag, attrs, text) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs))
    element.setAttribute(key, value);
  if (text != null) element.textContent = text;
  return element;
}
function drawMap(map) {
  const canvas = el("route-map");
  canvas.replaceChildren();
  const nodes = (map.places || []).map(([id, x, y, visits, landmark]) => ({
    id,
    x: -y * 48,
    y: x * 48,
    visits,
    landmark,
  }));
  el("map-count").textContent = nodes.length
    ? map.total +
      (map.total === 1 ? " place" : " places") +
      (map.total > nodes.length ? " · latest " + nodes.length + " shown" : "")
    : "";
  const g = map.guidance || {};
  el("map-place").textContent = g.place
    ? "At " + g.place + " · visit " + g.visits
    : "At the entrance";
  el("map-outcome").textContent = map.settling
    ? "Waiting for the view to settle after movement."
    : g.last_outcome || "Waiting for the first observation.";
  el("map-failed").textContent = g.unsuccessful?.join(" · ") || "None yet";
  el("map-options").textContent = g.untried?.join(", ") || "—";
  el("map-hint").textContent = g.hint || "";
  if (!nodes.length) return;
  // Separate overlapping schematic nodes without changing the exploration graph.
  for (let pass = 0; pass < 10; pass++)
    for (let i = 0; i < nodes.length; i++)
      for (let j = 0; j < i; j++) {
        const a = nodes[i],
          b = nodes[j];
        let dx = a.x - b.x,
          dy = a.y - b.y;
        if (dx === 0 && dy === 0) {
          dx = Math.cos(i + j);
          dy = Math.sin(i + j);
        }
        const length = Math.hypot(dx, dy);
        if (length < 25) {
          const adjust = (25 - length) / (length * 2);
          a.x += dx * adjust;
          a.y += dy * adjust;
          b.x -= dx * adjust;
          b.y -= dy * adjust;
        }
      }
  const xs = nodes.map((n) => n.x),
    ys = nodes.map((n) => n.y);
  const minX = Math.min(...xs),
    maxX = Math.max(...xs),
    minY = Math.min(...ys),
    maxY = Math.max(...ys);
  const width = Math.max(250, canvas.clientWidth),
    height = Math.max(140, canvas.clientHeight);
  const scale = Math.min(
    (width - 70) / Math.max(80, maxX - minX),
    (height - 56) / Math.max(80, maxY - minY),
  );
  for (const n of nodes) {
    n.x = width / 2 + (n.x - (minX + maxX) / 2) * scale;
    n.y = height / 2 + (n.y - (minY + maxY) / 2) * scale;
  }
  canvas.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  for (const [from, to] of map.links) {
    const a = byId.get(from),
      b = byId.get(to);
    if (a && b)
      canvas.append(
        svg("line", {
          x1: a.x,
          y1: a.y,
          x2: b.x,
          y2: b.y,
          stroke: "#6d8375",
          "stroke-width": 2,
        }),
      );
  }
  for (const n of nodes) {
    const here = n.id === map.current;
    const circle = svg("circle", {
      cx: n.x,
      cy: n.y,
      r: here ? 6 : 4,
      fill: here ? "#afefbf" : "#a2b2a4",
    });
    circle.append(
      svg(
        "title",
        {},
        "P" +
          n.id +
          " · " +
          n.visits +
          " visits" +
          (n.landmark ? " · " + n.landmark : ""),
      ),
    );
    canvas.append(circle);
    if (here || nodes.length <= 12)
      canvas.append(
        svg(
          "text",
          {
            x: n.x + 7,
            y: n.y + 13,
            fill: here ? "#aff1bd" : "#c5cec6",
            "font-size": 12,
          },
          "P" + n.id,
        ),
      );
    if (here) {
      function spoke(deg, len, color, pattern) {
        const a = (deg * Math.PI) / 180;
        canvas.append(
          svg("line", {
            x1: n.x,
            y1: n.y,
            x2: n.x + len * Math.cos(a),
            y2: n.y - len * Math.sin(a),
            stroke: color,
            "stroke-width": 3,
            "stroke-dasharray": pattern,
          }),
        );
      }
      for (const sector of map.failed_sectors)
        spoke(sector * 45, 24, "#ff9e6e", "3 3");
      spoke(map.heading, 14, "#aff1bd", "none");
    }
  }
}
async function refreshMap() {
  if (live.navigation_revision == null) return;
  const key = live.run + "/" + live.navigation_revision;
  if (key === mapKey) return;
  mapKey = key;
  try {
    const response = await fetch("/api/navigation");
    if (!response.ok) throw Error();
    const data = await response.json();
    if (mapKey === key && data.run === live.run) drawMap(data.map);
  } catch {
    if (mapKey === key) mapKey = "";
  }
}
poll();

let recordings = [],
  archiveVersion = "",
  playingId = "";
let preferredRecording = new URLSearchParams(location.search).get("recording");
let scrollToRecording = Boolean(preferredRecording) && location.hash === "#recordings";
function showRecording() {
  const entry = recordings.find((r) => r.id === el("recording-list").value);
  const ready = entry?.status === "Ready";
  el("recording-status").textContent = !entry
    ? "MP4s appear here when a run ends."
    : ready
      ? entry.result +
        " · " +
        (entry.kind === "comparison" ? entry.pairs + " paired encounters" : entry.steps + " decisions") +
        " · " +
        Math.floor(entry.duration / 60) +
        "m " +
        Math.floor(entry.duration % 60) +
        "s"
      : entry.status === "Failed"
        ? "Recording failed. " + entry.error
        : "Preparing the decision video…";
  const player = el("recording-player"),
    link = el("download-video");
  player.hidden = link.hidden = !ready;
  const id = ready ? entry.id : "";
  if (playingId === id) return;
  playingId = id;
  if (ready) {
    const url = "/recordings/" + encodeURIComponent(id) + "/agent.mp4";
    player.src = url;
    link.href = url + "?download";
  } else {
    player.removeAttribute("src");
    player.load();
    link.removeAttribute("href");
  }
}
el("recording-list").onchange = () => {
  preferredRecording = el("recording-list").value;
  showRecording();
};
async function refreshRecordings() {
  try {
    const response = await fetch("/api/recordings");
    if (!response.ok) throw Error();
    const entries = await response.json(),
      version = JSON.stringify(entries);
    if (version !== archiveVersion) {
      const select = el("recording-list"),
        prior = select.value;
      const keepSelection =
        prior !== recordings[0]?.id || !el("recording-player").paused;
      archiveVersion = version;
      recordings = entries;
      select.replaceChildren(
        ...entries.map((entry) => {
          const label =
            entry.scenario === "encounter"
              ? "First encounter"
              : "Level entrance";
          return new Option(entry.title ||
            new Date(entry.finished).toLocaleString() +
              " · " +
              label +
              " · " +
              entry.result,
            entry.id,
          );
        }),
      );
      select.disabled = !entries.length;
      if (preferredRecording && entries.some((r) => r.id === preferredRecording))
        select.value = preferredRecording;
      else if (keepSelection && entries.some((r) => r.id === prior))
        select.value = prior;
    }
    showRecording();
    if (scrollToRecording && playingId === preferredRecording) {
      el("recordings").scrollIntoView();
      scrollToRecording = false;
    }
  } catch {
    el("recording-status").textContent =
      "Recordings are temporarily unavailable.";
  }
  setTimeout(refreshRecordings, 3000);
}
refreshRecordings();
