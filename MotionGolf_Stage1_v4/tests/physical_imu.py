"""Build coherent IMU test trajectories from desired pose and world force.

Angle-only packets with level acceleration and zero gyro cannot represent a
tilting device. Rate-limit desired Euler angles and rotate acceleration into
the sensor frame, with corresponding body gyro rates (zero yaw).
"""

import math
from MotionGolf_Stage1_v4.controller import parse_packet
from MotionGolf_Stage1_v4.tests.test_upward_jump import v2_frame


class PhysicalImuTrace:
    def __init__(self):
        self.roll = self.pitch = 0.0
        self.tick = None

    def packet(self, data):
        packet = parse_packet(data.decode('ascii').strip())
        if packet is None or packet.accel_raw is None:
            return data
        dt = .02 if self.tick is None else ((packet.tick_ms - self.tick) & 0xffffffff) / 1000
        dt = min(.12, max(.001, dt))
        self.tick = packet.tick_ms
        # 225 degrees/s stays within the configured gyro range.
        step = 225 * dt
        delta_roll = (packet.roll - self.roll + 180) % 360 - 180
        delta_roll = max(-step, min(step, delta_roll))
        delta_pitch = max(-step, min(step, packet.pitch - self.pitch))
        midpoint_roll = math.radians(self.roll + delta_roll / 2)
        self.roll += delta_roll
        self.pitch += delta_pitch
        phi, theta = math.radians(self.roll), math.radians(self.pitch)
        ax, ay, az = (v / 16384 for v in packet.accel_raw)
        z_rotated = math.sin(theta) * ax + math.cos(theta) * az
        accel = (math.cos(theta) * ax - math.sin(theta) * az,
                 math.cos(phi) * ay + math.sin(phi) * z_rotated,
                 -math.sin(phi) * ay + math.cos(phi) * z_rotated)
        gyro = (delta_roll / dt,
                delta_pitch / dt * math.cos(midpoint_roll),
                -delta_pitch / dt * math.sin(midpoint_roll))
        return v2_frame(packet.tick_ms, roll=self.roll, pitch=self.pitch,
                        accel=accel, gyro=gyro, jump=int(packet.jump))
