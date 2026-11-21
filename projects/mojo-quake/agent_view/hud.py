"""Read the player's health from the visible 320×240 Quake status bar."""

import io
from contextlib import nullcontext
import math
import operator
import re
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# Use the project's shareware reader; original HUD art stays in the player's PAK.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from inspect_pak import pak_files


def open_frame(frame):
    return nullcontext(frame) if isinstance(frame, Image.Image) else Image.open(io.BytesIO(frame))


def normalized(image):
    values = list(
        image.convert("L").resize((12, 12), Image.Resampling.BILINEAR).getdata()
    )
    avg = sum(values) / len(values)
    centered = [n - avg for n in values]
    length = math.sqrt(sum(x * x for x in centered))
    return [x / length for x in centered] if length else [0.0] * len(values)


class NoticeFont:
    """Decode only the centered text actually drawn in a 320 × 240 game image."""

    def __init__(self, sheet, palette):
        atlas = np.frombuffer(sheet, np.uint8).reshape(128, 128)
        raw = np.array(
            [
                atlas[
                    c // 16 * 8 : c // 16 * 8 + 8, c % 16 * 8 : c % 16 * 8 + 8
                ].reshape(64)
                for c in range(33, 127)
            ]
        )
        self.mask = (raw != 0).astype("float32").T.copy()
        colors = np.frombuffer(palette, np.uint8).reshape(256, 3)
        self.ink = colors[raw].mean(axis=2).astype("float32").T.copy()
        self.norm = np.maximum(self.mask.sum(axis=0), 1)
        self.energy = np.sum(self.ink**2, axis=0)
        self.clear = 1 - self.mask

        labels = []
        for text in ("Monsters:", "Secrets :"):
            line = [colors[atlas[(ord(ch) // 16) * 8:(ord(ch) // 16 + 1) * 8,
                                 (ord(ch) % 16) * 8:(ord(ch) % 16 + 1) * 8]].mean(axis=2) for ch in text]
            labels.append(np.concatenate(line, axis=1))
        self.solo_labels = np.vstack(labels).astype(np.float32).ravel()
        self.solo_labels -= self.solo_labels.mean()
        self.solo_labels /= max(1., np.linalg.norm(self.solo_labels))

    def solo_scoreboard(self, frame):
        # Single player displays these two fixed labels instead of health digits on death.
        # The agent's input vocabulary has no show-scores command.
        patch = np.asarray(frame.crop((8, 220, 80, 236)).convert("L"), dtype=np.float32).ravel()
        patch -= patch.mean()
        return float(patch @ self.solo_labels) > .85 * max(1., np.linalg.norm(patch))

    def line(self, image, y):
        best = ""
        for offset in (0, 4):
            count = (320 - offset) // 8
            cells = (
                image[y : y + 8, offset : offset + count * 8]
                .reshape(8, count, 8)
                .transpose(1, 0, 2)
                .reshape(count, 64)
                .astype("float32")
            )
            background = np.median(cells, axis=1, keepdims=True)
            residual = (
                (cells * cells) @ self.mask - 2 * cells @ self.ink + self.energy
            ) / self.norm
            stray_ink = (np.maximum(cells - background - 18, 0) ** 2) @ self.clear / 64
            scores = np.maximum(residual, 0) + 0.35 * stray_ink
            closest = scores.argmin(axis=1)
            text = "".join(
                chr(33 + k) if error < 18**2 else " "
                for k, error in zip(closest, scores[np.arange(count), closest])
            )
            line = text.strip()
            centered = (
                abs((len(text) - len(text.lstrip())) - (len(text) - len(text.rstrip())))
                <= 2
            )
            if (
                centered
                and len(line) > len(best)
                and "   " not in line
                and re.search(r"[A-Za-z]{3}", line)
            ):
                best = line
        return best

    def read(self, jpeg):
        with open_frame(jpeg) as frame:
            if frame.size != (320, 240):
                return ""
            image = np.asarray(frame.convert("L"))
        for top in (84, 48):
            first = self.line(image, top)
            if first:
                lines = [first]
                for y in range(top + 8, top + 8 * 5, 8):
                    part = self.line(image, y)
                    if not part:
                        break
                    lines.append(part)
                return " ".join(lines)
        return ""


class HealthHUD:
    def __init__(self, pak):
        files = pak_files(pak)
        wad = files["gfx.wad"]
        palette = bytes(files["gfx/palette.lmp"])
        _, count, offset = struct.unpack_from("<4sii", wad)
        sprites = {}
        self.notice_font = None
        for i in range(count):
            start, size, _, _, _, _, name = struct.unpack_from(
                "<iiiBB2s16s", wad, offset + 32 * i
            )
            name = name.rstrip(b"\0").decode("ascii").lower()
            if name == "conchars" and size == 128 * 128:
                self.notice_font = NoticeFont(wad[start : start + size], palette)
                continue
            if not (name in ("sbar", "sb_key1", "sb_key2") or name.startswith(("num_", "anum_"))):
                continue
            w, h = struct.unpack_from("<ii", wad, start)
            image = Image.frombytes("P", (w, h), bytes(wad[start + 8 : start + size]))
            image.putpalette(palette)
            sprites[name] = image
        self.key_art = []
        for name in ("sb_key1", "sb_key2"):
            icon = sprites[name]
            mask = np.asarray(icon) != 255
            ref = np.asarray(icon.convert("L"))[mask].astype(np.float32)
            ref -= ref.mean()
            self.key_art.append((icon.size, mask, ref / max(1.,np.linalg.norm(ref))))
        self.results_art = []
        for name, x, y in (("complete", 64, 24), ("inter", 0, 56)):
            data = files["gfx/" + name + ".lmp"]
            w, h = struct.unpack_from("<ii", data)
            # Ignore transparent texels and the right-hand numeric fields.
            picture = Image.frombytes("P", (w, h), bytes(data[8 : 8 + w * h]))
            picture.putpalette(palette)
            width = min(w, 144)
            mask = np.asarray(picture)[:, :width] != 255
            ref = np.asarray(picture.convert("L"))[:, :width][mask].astype(np.float32)
            ref -= ref.mean()
            self.results_art.append(
                ((x, y, x + width, y + h), mask, ref / max(np.linalg.norm(ref), 1))
            )
        self.digits = {}
        self.glyphs = {}
        for x in (136, 160, 184, 248, 272, 296):
            bg = sprites["sbar"].crop((x, 0, x + 24, 24)).convert("RGB")
            choices = [("", [normalized(bg)])]
            for d in range(10):
                forms = []
                for style in ("num_", "anum_"):
                    sprite = sprites[style + str(d)]
                    rendered = bg.copy()
                    rendered.paste(
                        sprite.convert("RGB"),
                        (0, 0),
                        sprite.point([255] * 255 + [0], "L"),
                    )
                    forms.append(normalized(rendered))
                choices.append((str(d), forms))
            self.digits[x] = choices
            self.glyphs[x] = np.asarray([forms if len(forms)==2 else forms*2
                                          for _,forms in choices],dtype=np.float32)

    def key_mask(self, jpeg):
        bits = 0
        with open_frame(jpeg) as frame:
            if frame.size != (320,240):
                return bits
            for i, ((w,h), mask, ref) in enumerate(self.key_art):
                x=192+16*i
                values = np.asarray(frame.crop((x,200,x+w,200+h)).convert("L"))[mask].astype(np.float32)
                values -= values.mean()
                if float(values @ ref) > .86 * max(1.,np.linalg.norm(values)):
                    bits |= 1 << i
        return bits

    def completed(self, jpeg):
        with open_frame(jpeg) as frame:
            if frame.size != (320, 240):
                return False
            gray = frame.convert("L")
            for box, mask, template in self.results_art:
                values = np.asarray(gray.crop(box))[mask].astype(np.float32)
                values -= values.mean()
                if float(values @ template) < 0.82 * max(1, np.linalg.norm(values)):
                    return False
        return True

    def read(self, jpeg):
        with open_frame(jpeg) as frame:
            return self.health_value(frame)

    def read_status(self, jpeg):
        with open_frame(jpeg) as frame:
            return self.health_value(frame), self.number(frame, 248)

    def health_value(self, frame):
        value = self.number(frame, 136)
        if value is None and frame.size == (320, 240) and self.notice_font and self.notice_font.solo_scoreboard(frame):
            return 0
        return value

    def number(self, frame, left):
        if frame.size != (320, 240):
            return None
        result = []
        for x in (left, left + 24, left + 48):
            choices = self.digits[x]
            values = normalized(frame.crop((x, 216, x + 24, 240)))
            correlations = (self.glyphs[x] @ np.asarray(values,dtype=np.float32)).max(axis=1)
            order = np.argsort(correlations)
            best, runner_up = order[-1],order[-2]
            if correlations[best] < .76 or correlations[best]-correlations[runner_up] < .035:
                return None
            result.append(choices[best][0])
        text = "".join(result)
        if (
            not text
            or (len(text) > 1 and text[0] == "0")
            or result != [""] * (3 - len(text)) + list(text)
        ):
            return None
        return int(text)


class DamageSense:
    """Only confident numeric drops trigger an evasive move. Pickups rebase the counter."""

    def __init__(self, reader):
        self.reader = reader
        self.health = self.ammo = None
        self.last_hit = -10000
        self.last_reaction = -10000
        self.last_enemy = None
        self.scanned = False
        self.pending = None
        self.notice_candidate = ""
        self.notice = ""
        self.notice_tick = self.last_read_notice = -10000
        self.health_gain = None
        self.last_overheal_drop = None

    def see_enemy(self, point, observation_tick):
        self.last_enemy = observation_tick if point is not None else None

    def strafe_after_hit(self, tick):
        if not 0 <= tick - self.last_hit <= 110:
            return 0
        # Alternate a short sideways dodge; keep input bounded between observations.
        return 235 if (tick // 42) % 2 else -235

    def context(self, tick):
        return {
            "visible_hp": self.health,
            "active_ammo": self.ammo,
            **(
                {
                    "game_message": self.notice,
                    "message_ticks_ago": tick - self.notice_tick,
                }
                if self.notice and tick - self.notice_tick <= 12 * 72
                else {}
            ),
            **(
                {"recent_health_gain": self.health_gain[1]}
                if self.health_gain and tick - self.health_gain[0] <= 5 * 72
                else {}
            ),
            "hit_ticks_ago": tick - self.last_hit
            if tick - self.last_hit <= 216
            else None,
        }

    def take_pending(self):
        hit, self.pending = self.pending, None
        return hit

    def watch(self, jpeg, tick):
        font = getattr(self.reader, "notice_font", None)
        if font and tick - self.last_read_notice >= 12:
            self.last_read_notice = tick
            text = font.read(jpeg)
            if text and text == self.notice_candidate:
                self.notice, self.notice_tick = text, tick
            self.notice_candidate = text
        if hasattr(self.reader, "read_status"):
            hp, self.ammo = self.reader.read_status(jpeg)
        else:
            hp = self.reader.read(jpeg)
        if hp is None:
            return
        before = self.health
        self.health = hp
        if before is not None and hp > before:
            self.health_gain = tick, hp - before
            self.last_overheal_drop = None
        if before is None or hp >= before or hp <= 0:
            return
        if before > 100 and hp >= 100 and hp == before - 1:
            previous = self.last_overheal_drop
            self.last_overheal_drop = tick
            if previous is not None and abs(tick - previous - 72) <= 8:
                # Quake drains excess health on a one-second clock.
                return
        else:
            self.last_overheal_drop = None
        if tick - self.last_hit > 216:
            self.scanned = False
        self.last_hit = tick
        if tick - self.last_reaction < 72:
            return
        enemy_recent = self.last_enemy is not None and tick - self.last_enemy <= 72
        scan = not enemy_recent and not self.scanned
        self.pending = {
            "from_hp": before,
            "to_hp": hp,
            "detected_tick": tick,
            "action": "evade_and_scan" if scan else "jump_back",
        }
        self.scanned |= scan
        self.last_reaction = tick
