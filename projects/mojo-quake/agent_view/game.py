"""Native Quake runs in its own process. This pipe is the transport boundary."""

import hashlib
import io
import os
import subprocess
import tempfile
import zlib
from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

from PIL import Image, ImageChops, ImageStat


def view_signature(jpeg):
    """Sample the level geometry above the weapon and HUD for movement feedback."""
    with Image.open(io.BytesIO(jpeg)) as image:
        return image.crop((12, 8, 308, 165)).convert("L").resize((48, 28))


def visual_change(before, after):
    difference = ImageChops.difference(before, view_signature(after))
    return round(100 * ImageStat.Stat(difference).mean[0] / 255, 1)


class NativePipe:
    def __init__(self, command, env, *, raw_images=False):
        self.raw_images = raw_images
        self.events = Queue()
        self.process = subprocess.Popen(
            command,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            Thread(target=self._read, daemon=True).start()
            self.capabilities = self.expect("ready")
        except BaseException:
            self.close()
            raise

    def send(self, commands):
        self.process.stdin.write((commands + "\n").encode())
        self.process.stdin.flush()

    def state(self):
        self.send("state")
        return self.expect("state")

    def _read(self):
        try:
            capabilities = set()
            stream = self.process.stdout
            for line in iter(stream.readline, b""):
                if line.startswith(b"MQ_AGENT_CAPS "):
                    capabilities.update(line.decode().split()[1:])
                elif line.strip() == b"MQ_AGENT_READY 1":
                    self.events.put(("ready", capabilities))
                elif line.strip() == b"MQ_GLANCE_MISSED":
                    self.events.put(("error", "Preview camera redraw unavailable"))
                elif line.startswith(b"MQ_RESTORE_SLOT "):
                    self.events.put(("restored", int(line.split()[1])))
                elif line.startswith(b"MQ_SAVE_SLOT "):
                    self.events.put(("saved", int(line.split()[1])))
                elif line.startswith(b"MQ_FRAME "):
                    _, tick, width, height, kind = line.split()
                    w, h = int(width), int(height)
                    if (w, h) != (320, 240):
                        raise ValueError("Unexpected game frame size")
                    if kind == b"INDEXED":
                        palette = stream.read(768)
                        image = Image.frombytes("P", (w, h), stream.read(w * h))
                        image.putpalette(palette)
                        image = image.convert("RGB")
                    elif kind == b"RGB_BOTTOM_UP":
                        image = Image.frombytes(
                            "RGB", (w, h), stream.read(3 * w * h), "raw", "RGB", 0, -1
                        )
                    else:
                        raise ValueError("Unknown native framebuffer format")
                    if self.raw_images:
                        self.events.put(("frame", (int(tick), image)))
                    else:
                        buffer = io.BytesIO()
                        image.save(buffer, "JPEG", quality=82)
                        self.events.put(("frame", (int(tick), buffer.getvalue())))
                elif line.startswith(b"MQ_STATE "):
                    state = dict(
                        field.split("=", 1) for field in line.decode().split()[1:]
                    )
                    self.events.put(("state", state))
        except (ValueError, OSError) as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.events.put(("error", "The native game exited."))

    def expect(self, kind):
        try:
            name, value = self.events.get(timeout=12)
        except Empty:
            raise RuntimeError(
                "Game response timed out. Rebuild Quake with agent-frame support."
            ) from None
        if name != kind:
            raise RuntimeError(
                value if name == "error" else f"Expected {kind}, received {name}"
            )
        return value

    def close(self):
        child = getattr(self, "process", None)
        if child:
            try:
                child.stdin.close()
            except BrokenPipeError:
                pass
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            child.stdout.close()


class Game:
    def __init__(self, binary, media, gpu=False, start_map="e1m1", *, show_weapon=True, reference_camera=False):
        self.profile = tempfile.TemporaryDirectory(prefix="mojo-quake-agent-")
        self.slots = {}
        self._lineage = object()
        self.tick_offset = 0
        self.tick = 0
        self.yaw = 90
        self.pitch = 0
        env = dict(
            os.environ, MOJO_QUAKE_PROFILE=self.profile.name, SDL_AUDIODRIVER="dummy"
        )
        env.pop("MODULAR_API_KEY", None)
        env.pop("TYPESAFE_API_KEY", None)
        if not gpu:
            env["SDL_VIDEODRIVER"] = "dummy"
        cmd = [
            binary,
            "-basedir",
            media,
            "-window",
            "-width",
            "320",
            "-height",
            "240",
            "-mqhidden",
            "-noudp",
            "-nocdaudio",
            "-noconinput",
            "-mqfast",
            "-mqagent",
            "-mqreplay",
            "-",
            "+scr_conspeed",
            "99999",
            "+con_notifytime",
            "0",
            "+scr_sbaralpha",
            "1",
            "+skill",
            "1",
        ]
        if reference_camera:
            cmd.append("-mqpreview")
        if not show_weapon:
            cmd[1:1] = ["+r_drawviewmodel", "0"]
        self.command = cmd
        self.environment = env
        try:
            self.pipe = NativePipe([*cmd, "+map", start_map], env)
        except BaseException:
            self.profile.cleanup()
            raise

    def save_checkpoint(self, slot):
        if type(slot) is not int or not 1 <= slot <= 999999 or slot in self.slots:
            raise ValueError("Expected a new numeric checkpoint ID")
        if "native_save" not in self.pipe.capabilities:
            raise RuntimeError("Rebuild Quake to enable agent saves")
        name = f"agent_{slot:06d}"
        path = Path(self.profile.name) / "id1" / (name + ".sav")
        path.parent.mkdir(exist_ok=True)
        if path.exists():
            raise FileExistsError(path)
        self.pipe.send(f"save_slot {slot}")
        if self.pipe.expect("saved") != slot or not path.is_file():
            raise RuntimeError("Quake did not create the requested save")
        digest = self.pipe.state()["hash"]
        fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
        self.slots[slot] = (digest, fingerprint, self.yaw, self.pitch, path)
        return {"state_hash": digest, "save_sha256": fingerprint}

    def archive_checkpoint(self, slot, directory):
        path = self.slots[slot][-1]
        directory.mkdir(exist_ok=True)
        target = directory / path.name
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
            temp = Path(output.name)
            try:
                output.write(path.read_bytes())
                output.flush()
                os.fsync(output.fileno())
            except BaseException:
                temp.unlink(missing_ok=True)
                raise
        try:
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

    def preview_source(self):
        """Capture a transient native save belonging to this game for camera-only rollouts."""
        slot = 999999
        while slot in self.slots:
            slot -= 1
        receipt = self.save_checkpoint(slot)
        _, _, yaw, pitch, path = self.slots.pop(slot)
        try:
            data = path.read_bytes()
            return PreviewSource(
                self.command,
                self.environment,
                data,
                receipt,
                self.tick,
                yaw,
                pitch,
                self._lineage,
            )
        finally:
            path.unlink(missing_ok=True)

    def load_checkpoint(self, slot):
        if type(slot) is not int or slot not in self.slots:
            raise ValueError("Checkpoint was not created by this run")
        digest, fingerprint, yaw, pitch, path = self.slots[slot]
        if hashlib.sha256(path.read_bytes()).hexdigest() != fingerprint:
            raise ValueError("Quake save file changed")
        replacement = NativePipe([*self.command, "+load", path.stem], self.environment)
        try:
            if replacement.state()["hash"] != digest:
                raise ValueError("Restored gameplay differs from the saved state")
        except BaseException:
            replacement.close()
            raise
        previous, self.pipe = self.pipe, replacement
        self.tick_offset = self.tick
        self.yaw, self.pitch = yaw, pitch
        previous.close()
        return {"state_hash": digest, "save_sha256": fingerprint}

    def move(
        self, ticks, forward=0, side=0, buttons=0, *, up=0, impulse=0, evaluate=False
    ):
        row = (
            f"{ticks} {forward} {side} {up} {self.yaw} {self.pitch} {buttons} {impulse}"
        )
        self.pipe.send(row + ("\nstate" if evaluate else ""))
        tick, jpg = self.pipe.expect("frame")
        self.tick += ticks
        if self.tick != self.tick_offset + tick:
            raise RuntimeError("Game and controller frame numbers differ")
        metrics = self.pipe.expect("state") if evaluate else None
        return jpg, metrics, row

    def close(self):
        try:
            self.pipe.close()
        finally:
            self.profile.cleanup()


class PreviewSource:
    """Opaque game-owned snapshot. Search receives a camera interface."""

    def __init__(self, command, env, data, receipt, tick, yaw, pitch, lineage):
        self.lineage = lineage
        self._command = tuple(command)
        self._env = env
        self._data = data
        self._digest = receipt["state_hash"]
        if hashlib.sha256(data).hexdigest() != receipt["save_sha256"]:
            raise ValueError("Lookahead snapshot differs from the saved game")
        self.tick, self.yaw, self.pitch = tick, yaw, pitch

    def pack(self):
        return PackedPreview(self)

    def open_camera(self, *, raw_images=False):
        return PreviewCamera(self, raw_images=raw_images)

    @property
    def receipt(self):
        return {"source_tick": self.tick, "source_hash": self._digest}


class PackedPreview:
    """Memory-bounded transport for a hypothetical save. Expose only a camera lineage."""
    def __init__(self, source):
        self.blob = zlib.compress(source._data, level=1)
        self.command, self.env, self.digest = source._command, source._env, source._digest
        self.lineage,self.tick,self.yaw,self.pitch = source.lineage,source.tick,source.yaw,source.pitch

    @property
    def packed_size(self):
        return len(self.blob)

    def unpack(self):
        data = zlib.decompress(self.blob)
        receipt = {"state_hash": self.digest, "save_sha256": hashlib.sha256(data).hexdigest()}
        return PreviewSource(self.command, self.env, data, receipt, self.tick, self.yaw, self.pitch, self.lineage)


class PreviewCamera:
    """A disposable Quake instance. Movement returns only rendered RGB."""

    def __init__(self, source, *, raw_images=False):
        self.raw_images = raw_images
        self.profile = tempfile.TemporaryDirectory(prefix="quake-own-save-preview-")
        self.source = source
        self.env = dict(source._env, MOJO_QUAKE_PROFILE=self.profile.name)
        directory = Path(self.profile.name) / "id1"
        try:
            directory.mkdir()
            (directory / "origin.sav").write_bytes(source._data)
            self.pipe = self._open("origin", source._digest)
        except BaseException:
            self.profile.cleanup()
            raise
        self.base = None

    def _open(self, name, digest):
        pipe = NativePipe(
            [*self.source._command, "-mqpreview", "+load", name], self.env, raw_images=self.raw_images
        )
        try:
            if pipe.state()["hash"] != digest:
                raise ValueError("Lookahead branch did not start at its own save")
        except BaseException:
            pipe.close()
            raise
        return pipe

    def snapshot(self, yaw, pitch):
        """Fork this camera's own simulated state without disturbing its rewind point."""
        slot = 2
        path = Path(self.profile.name) / "id1/agent_000002.sav"
        path.unlink(missing_ok=True)
        self.pipe.send(f"save_slot {slot}")
        if self.pipe.expect("saved") != slot or not path.is_file():
            return None
        data = path.read_bytes()
        receipt = {"state_hash": self.pipe.state()["hash"], "save_sha256": hashlib.sha256(data).hexdigest()}
        return PreviewSource(self.source._command, self.source._env, data, receipt,
                             self.source.tick, yaw, pitch, self.source.lineage)

    def pin(self):
        path = Path(self.profile.name) / "id1/agent_000001.sav"
        path.unlink(missing_ok=True)
        self.pipe.send("save_slot 1")
        if self.pipe.expect("saved") != 1 or not path.is_file():
            raise RuntimeError("Quake could not save the hypothetical prefix")
        self.base = self.pipe.state()["hash"]

    @contextmanager
    def endpoint(self):
        """Temporarily compare controls at one candidate endpoint, keeping the common origin."""
        if self.base is None:
            raise ValueError("No preview origin")
        path = Path(self.profile.name) / "id1/agent_000001.sav"
        original, digest = path.read_bytes(), self.base
        try:
            self.pin()
            yield
        finally:
            path.write_bytes(original)
            self.base = digest

    def rewind(self):
        if self.base is None:
            raise ValueError("Lookahead branch point has not been pinned")
        if "preview_rewind" in self.pipe.capabilities:
            self.pipe.send("restore_slot 1")
            if (
                self.pipe.expect("restored") == 1
                and self.pipe.state()["hash"] == self.base
            ):
                return
        self.pipe.close()
        self.pipe = self._open("agent_000001", self.base)

    def rebase(self, source):
        if source.lineage is not self.source.lineage:
            raise ValueError("Preview snapshots must originate in this run")
        path = Path(self.profile.name) / "id1/agent_000001.sav"
        path.write_bytes(source._data)
        self.source = source
        self.base = source._digest
        self.rewind()

    def glance(self, yaw, pitch):
        """Look in another direction from the avatar's current camera origin."""
        if "camera_glance" not in self.pipe.capabilities:
            raise RuntimeError("Rebuild the preview engine for camera glances")
        self.pipe.send(f"glance {yaw:.3f} {pitch:.3f}")
        return self.pipe.expect("frame")[1]

    def frame(self, ticks, forward, side, up, yaw, pitch, buttons=0):
        if not 1 <= ticks <= 180:
            raise ValueError("Lookahead moves must be short")
        self.pipe.send(
            f"{ticks} {forward} {side} {up} {yaw:.4f} {pitch:.4f} {buttons} 0"
        )
        _, frame = self.pipe.expect("frame")
        return frame

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            self.pipe.close()
        finally:
            self.profile.cleanup()
