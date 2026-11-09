"""Playable upward gestures with brief downward suppression and fixed cooldown.

Lateral motion and wrist rotation do not veto a lift. Mild downward preparation
is tolerated; occasional braking false positives are an accepted tradeoff.
"""

from collections import deque
import math


def _norm(v):
    return math.sqrt(sum(x * x for x in v))


def _unit(v):
    length = _norm(v)
    return tuple(x / length for x in v) if length > 1e-9 else (0.0, 0.0, 1.0)


class UpwardJumpDetector:
    MIN_THRESHOLD = 0.10
    MAX_THRESHOLD = 0.80
    DEFAULT_THRESHOLD = 0.30
    COOLDOWN_SECONDS = 0.70
    DOWNWARD_THRESHOLD_G = -0.25
    DOWNWARD_HOLDOFF_SECONDS = 0.12
    TRANSITION_REST_SECONDS = 0.08

    def __init__(self, threshold_g=DEFAULT_THRESHOLD):
        self.set_threshold(threshold_g)

    def set_threshold(self, value):
        if not math.isfinite(value) or not self.MIN_THRESHOLD <= value <= self.MAX_THRESHOLD:
            raise ValueError("Upward threshold must be between 0.10 and 0.80 g")
        self.threshold_g = float(value)
        self.reset()

    def reset(self, *, preserve_reference=False):
        reference = ((self._gravity, self._bias, self._rest_g, self._tick)
                     if preserve_reference and getattr(self, "_gravity", None) is not None
                     else None)
        self.state = "settling"
        self.vertical_g = self.horizontal_g = 0.0
        self.peak_g = 0.0
        self._rest_g = 1.0
        self._tick = None
        self._gravity = None
        self._bias = (0.0, 0.0, 0.0)
        self._initial = deque(maxlen=20)
        self._time = self._above_time = 0.0
        self._candidate_at = self._locked_at = 0.0
        self._downward_until = 0.0
        self._released = False
        if reference is not None:
            self._gravity, self._bias, self._rest_g, self._tick = reference
            # Keep calibration, but require the old upward force to be released.
            self.state = "waiting"

    def _lock(self):
        self.state = "locked"
        self._locked_at = self._time
        self._above_time = 0.0
        self._released = False

    def update(self, accel_g, gyro_dps, tick_ms):
        """Return one event. Device sample time, not host arrival time, sets dt."""
        if self._tick is None:
            self._tick = tick_ms
            dt = 0.02
        else:
            delta = (tick_ms - self._tick) & 0xFFFFFFFF
            if delta == 0:
                return False
            if delta > 120:
                self.reset()
                self._tick = tick_ms
                return False
            self._tick = tick_ms
            dt = delta / 1000.0
        self._time += dt
        magnitude = _norm(accel_g)
        if self._gravity is None:
            if abs(magnitude - 1.0) > 0.08 or _norm(gyro_dps) > 35.0:
                self._initial.clear()
                return False
            self._initial.append((accel_g, gyro_dps))
            if len(self._initial) < self._initial.maxlen:
                return False
            if any(max(row[0][axis] for row in self._initial) -
                   min(row[0][axis] for row in self._initial) > 0.06 for axis in range(3)):
                return False
            mean_accel = tuple(sum(row[0][i] for row in self._initial) /
                               len(self._initial) for i in range(3))
            self._rest_g = _norm(mean_accel)
            self._gravity = _unit(mean_accel)
            self._bias = tuple(sum(row[1][i] for row in self._initial) /
                               len(self._initial) for i in range(3))
            self.state = "ready"
            return False

        gyro = tuple(a - b for a, b in zip(gyro_dps, self._bias))
        wx, wy, wz = (math.radians(x) for x in gyro)
        gx, gy, gz = self._gravity
        # Gravity is fixed in world space; its body-frame derivative is g x w.
        self._gravity = _unit((gx + (gy * wz - gz * wy) * dt,
                               gy + (gz * wx - gx * wz) * dt,
                               gz + (gx * wy - gy * wx) * dt))
        projected = sum(a * g for a, g in zip(accel_g, self._gravity))
        self.vertical_g = projected - self._rest_g
        self.horizontal_g = _norm(tuple(a - projected * g
                                        for a, g in zip(accel_g, self._gravity)))
        gyro_speed = _norm(gyro)
        if self.state == "ready" and self.vertical_g > 0.08:
            self.peak_g = self.vertical_g
        elif self.state in {"lifting", "locked"}:
            self.peak_g = max(self.peak_g, self.vertical_g)
        still = (abs(self.vertical_g) < 0.02 and self.horizontal_g < 0.08
                 and gyro_speed < 20.0)
        # Correct slow attitude drift only under near-rest conditions.
        if still:
            measured = _unit(accel_g)
            alpha = 1.0 - math.exp(-dt / 1.0)
            self._gravity = _unit(tuple((1 - alpha) * g + alpha * a
                                        for g, a in zip(self._gravity, measured)))

        if self.vertical_g <= self.threshold_g * 0.5:
            self._released = True
        if self.vertical_g < self.DOWNWARD_THRESHOLD_G:
            self._downward_until = self._time + self.DOWNWARD_HOLDOFF_SECONDS

        if self.state == "waiting":
            if self._released and self._time >= self.TRANSITION_REST_SECONDS - 1e-9:
                self.state = "ready"
            return False

        if self.state == "locked":
            if self._released and self._time - self._locked_at >= self.COOLDOWN_SECONDS - 1e-9:
                self.state = "ready"
            return False

        # Clear only this candidate after a strong downward pulse. There is no
        # latched rejection or requirement for precise stillness to resume.
        if self._time < self._downward_until - 1e-9:
            self.state = "ready"
            self._above_time = 0.0
            return False
        if self.state == "ready":
            if self.vertical_g <= 0.08:
                return False
            self.state = "lifting"
            self._candidate_at = self._time
            self._above_time = 0.0
        if self.state == "lifting":
            self._above_time = self._above_time + dt if self.vertical_g >= self.threshold_g else 0.0
            if self._above_time >= 0.04 - 1e-9:
                self._lock()
                return True
            if self.vertical_g < 0.04:
                self.state = "ready"
                self._above_time = 0.0
            elif self._time - self._candidate_at > 0.25:
                self.state = "ready"
                self._above_time = 0.0
        return False
