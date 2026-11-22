// Keep the large GPU module off the audio/2D startup path.
(() => {
  const dialog = document.querySelector("#inspection");
  const canvas = dialog.querySelector("canvas");
  const toggle = document.querySelector("#inspect-toggle"),
    frame = document.querySelector(".frame");
  const guide = document.querySelector("#guide");
  const status = document.querySelector("#inspect-status");
  let viewer,
    loading,
    failed = false;
  function fail() {
    viewer?.hide();
    failed = true;
    dialog.dataset.failed = "true";
    dialog.dataset.ready = "false";
    status.textContent =
      "3D view needs WebGL 2. Open the local sampler in a browser with graphics acceleration.";
  }
  async function open() {
    if (dialog.open || document.querySelector("#help").open) return;
    dialog.dataset.ready = "false";
    dialog.show();
    frame.inert = true;
    guide.inert = true;
    toggle.setAttribute("aria-expanded", "true");
    toggle.firstChild.textContent = "2D view ";
    canvas.focus({ preventScroll: true });
    if (failed) {
      fail();
      return;
    }
    if (!viewer) status.textContent = "Loading 3D view…";
    try {
      loading ??= import("./inspect-model.mjs").then((m) =>
        m.createInspection(canvas, fail),
      );
      viewer = await loading;
      if (!dialog.open || failed) return;
      status.textContent = "";
      viewer.show();
      dialog.dataset.ready = "true";
    } catch {
      fail();
    }
  }
  function back() {
    if (!viewer || failed || dialog.dataset.ready !== "true") {
      dialog.close();
      return;
    }
    if (canvas.dataset.pose === "returning") return;
    viewer.returnToPanel(() => dialog.close());
  }
  dialog.addEventListener("cancel", (e) => {
    e.preventDefault();
    back();
  });
  dialog.addEventListener("close", () => {
    if (!dialog.open) {
      viewer?.hide();
      frame.inert = false;
      guide.inert = false;
      toggle.setAttribute("aria-expanded", "false");
      toggle.firstChild.textContent = "3D view ";
      if (toggle.getClientRects().length) toggle.focus({ preventScroll: true });
    }
  });
  toggle.addEventListener("click", () => (dialog.open ? back() : open()));
  document.querySelector("#inspect-close").addEventListener("click", back);
  window.addEventListener(
    "keydown",
    (event) => {
      if (event.altKey || event.metaKey || event.ctrlKey) return;
      if (
        (event.code === "KeyP" && !document.querySelector("#help").open) ||
        (event.code === "Escape" && dialog.open)
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (!event.repeat) {
          if (dialog.open) back();
          else open();
        }
      }
    },
    true,
  );
  if (new URLSearchParams(location.search).get("view") === "3d") open();
})();
