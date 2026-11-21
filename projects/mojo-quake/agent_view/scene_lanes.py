"""Infer local passage choices from a single RGB frame, off the simulation thread."""

import math
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np


class SceneEstimator:
    def __init__(self, weights):
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 3
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(
            str(weights), options, providers=["CPUExecutionProvider"]
        )
        self.input = self.session.get_inputs()[0].name

    def read(self, jpeg, pitch=0, *, openings=False):
        start = time.monotonic()
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)[
            :192, :, ::-1
        ]
        small = (
            cv2.resize(image, (196, 112), interpolation=cv2.INTER_CUBIC).astype(
                np.float32
            )
            / 255
        )
        tensor = (small - np.float32([0.485, 0.456, 0.406])) / np.float32(
            [0.229, 0.224, 0.225]
        )
        surface = self.session.run(None, {self.input: tensor.transpose(2, 0, 1)[None]})[
            0
        ].squeeze()
        relative = cv2.resize(surface, (320, 192))
        result = self.directions(relative, pitch)
        if openings:
            horizon = round(119.5 - 160 * math.tan(math.radians(pitch)))
            band = relative[max(0, horizon - 24) : min(192, horizon + 15)]
            values = np.array(
                [np.quantile(band[:, x - 9 : x + 10], 0.68) for x in range(12, 311, 8)]
            )
            x = 12 + 8 * int(
                np.argmin(np.convolve(values, [1 / 3] * 3, mode="valid")) + 1
            )
            result["opening_yaw"] = round(math.degrees(math.atan((159.5 - x) / 160)), 2)
        result["ms"] = round((time.monotonic() - start) * 1000, 1)
        return result

    @staticmethod
    def directions(relative, pitch):
        horizon = 119.5 - 160 * math.tan(math.radians(pitch))
        fits = []
        extent = float(np.ptp(relative))
        if not math.isfinite(extent) or extent < 0.001:
            return {"pick": "scan", "lanes": {}, "floor_support": 0}
        # Estimate floor slope beside the first-person weapon when a plane is visible.
        ys = np.arange(max(132, round(horizon + 18)), 189, 3)
        if len(ys) >= 6:
            for x in range(8, 313, 8):
                if 125 < x < 195:
                    continue
                v = np.median(relative[ys, x - 2 : x + 3], axis=1)
                slope, offset = np.polyfit(ys - horizon, v, 1)
                residual = np.abs((ys - horizon) * slope + offset - v).mean()
                if slope > max(0.002, 0.0008 * extent) and residual < 0.18 * max(
                    0.001, np.ptp(v)
                ):
                    fits.append((slope, offset))
        floor = np.median(fits, axis=0) if fits else None
        lanes = {}
        y0 = max(12, round(horizon - 23))
        y1 = min(179, round(horizon + 25))
        if y1 - y0 < 10:
            return {"pick": "scan", "lanes": {}, "floor_support": 0}
        for name, angle in (("left", -32), ("center", 0), ("right", 32)):
            x = round(159.5 + 160 * math.tan(math.radians(angle)))
            disparity = float(np.quantile(relative[y0:y1, x - 15 : x + 16], 0.65))
            length = (
                160 * 46 * float(floor[0]) / max(0.001, disparity - float(floor[1]))
                if floor is not None
                else None
            )
            lanes[name] = {
                "relative": round(disparity, 3),
                "range_estimate": None
                if length is None
                else round(min(length, 2000), 1),
            }
        chosen = min(lanes, key=lambda name: lanes[name]["relative"])
        distance = lanes[chosen]["range_estimate"]
        return {
            "pick": "scan" if distance is not None and distance < 80 else chosen,
            "lanes": lanes,
            "floor_support": len(fits),
        }


class LaneSense:
    def __init__(self, model):
        self.model = model
        self.pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="quake-camera-lanes"
        )
        self.future = None
        self.generation = 0
        self.last_tick = -10000
        self.result = None
        self.last_error = None

    def update(self, jpeg, tick, yaw, pitch):
        if self.future and self.future[0].done():
            job, generation, stamp, az, el = self.future
            self.future = None
            failure = job.exception()
            if failure is not None:
                # Vision is optional; leave ordinary controls available while it recovers.
                self.last_error = type(failure).__name__
                self.result = None
                self.last_tick = tick + 3 * 72
                return
            result = job.result()
            self.last_error = None
            if generation == self.generation:
                self.result = dict(
                    result, source_tick=stamp, source_yaw=az, source_pitch=el
                )
        if self.future is None and tick - self.last_tick >= 12 and abs(pitch) < 24:
            self.last_tick = tick
            self.future = (
                self.pool.submit(self.model.read, jpeg, pitch),
                self.generation,
                tick,
                yaw,
                pitch,
            )

    def current(self, tick, yaw, pitch):
        r = self.result
        if not r or tick - r["source_tick"] > 36:
            return None
        turn = (yaw - r["source_yaw"] + 180) % 360 - 180
        if abs(turn) > 12 or abs(pitch - r["source_pitch"]) > 8:
            return None
        info = dict(r)
        if r["pick"] != "scan":
            angle = {"left": -32, "center": 0, "right": 32}[r["pick"]] + turn
            point = 50 + 50 * math.tan(math.radians(angle))
            info["point"] = [round(max(0, min(100, point)), 1), 55]
        return info

    def reset(self):
        self.generation += 1
        self.last_tick = -10000
        self.result = None

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
