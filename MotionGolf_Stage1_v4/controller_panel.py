"""Controller connection and player-adjustable jump settings overlay."""

import pygame

if __package__:
    from .settings import load_settings, save_settings
else:
    from settings import load_settings, save_settings


class ControllerPanel:
    def __init__(self, controller):
        self.controller = controller
        self.settings = load_settings()
        controller.set_jump_threshold(self.settings["jump_threshold_g"])
        self.mode = "STM32"
        self.open = True
        self.dragging = False
        self.jump_tests = 0
        self.message = "Connect, hold a comfortable neutral pose, then calibrate."
        self.ports = []
        self.selected = 0
        self._was_calibrating = False
        self.slider = pygame.Rect(170, 350, 600, 14)
        self.buttons = {
            "stm32": pygame.Rect(140, 120, 180, 36),
            "keyboard": pygame.Rect(335, 120, 180, 36),
            "close": pygame.Rect(850, 85, 110, 36),
            "start": pygame.Rect(700, 85, 135, 36),
            "previous": pygame.Rect(140, 190, 45, 36),
            "next": pygame.Rect(455, 190, 45, 36),
            "refresh": pygame.Rect(520, 190, 120, 36),
            "connect": pygame.Rect(655, 190, 140, 36),
            "calibrate": pygame.Rect(795, 245, 165, 36),
            "light": pygame.Rect(170, 385, 170, 36),
            "normal": pygame.Rect(355, 385, 170, 36),
            "firm": pygame.Rect(540, 385, 170, 36),
        }
        self.refresh_ports()
        preferred = self.settings["port"] or self.controller.detect_port()
        for index, (port, _) in enumerate(self.ports):
            if port == preferred:
                self.selected = index
                self.connect_selected()
                break

    @property
    def ready(self):
        return self.mode == "Keyboard" or (self.controller.connected
                and self.controller.calibrated and not self.controller.calibrating)

    @property
    def readiness_reason(self):
        if self.mode == "Keyboard":
            return "Keyboard ready."
        if self.controller.last_sensor_error:
            return "Sensor I2C fault: reconnect/check MPU wiring before resuming."
        if not self.controller.connected:
            return "Waiting for valid data. Check device and selected port."
        if self.controller.calibrating:
            return "Hold steady: calibration in progress."
        if not self.controller.calibrated:
            return "Data received. Press Calibrate (F4) before resuming."
        return "Controller ready."

    def refresh_ports(self):
        current = self.ports[self.selected][0] if self.ports else None
        try:
            self.ports = self.controller.available_ports()
        except (ImportError, OSError) as exc:
            self.ports = []
            self.message = f"Cannot list ports: {exc}"
        self.selected = next((i for i, p in enumerate(self.ports) if p[0] == current), 0)

    def _save(self):
        self.settings["jump_threshold_g"] = self.controller.detector.threshold_g
        try:
            save_settings(self.settings)
        except (OSError, ValueError) as exc:
            self.message = f"Settings not saved: {exc}"

    def connect_selected(self):
        if not self.ports:
            self.message = "No port selected. Connect the device and Refresh."
            return
        port = self.ports[self.selected][0]
        if self.controller.connect(port):
            self.settings["port"] = port
            self.message = "Port open. Wait for data, then Calibrate."
            self._save()
        else:
            self.message = self.controller.last_error

    def set_mode(self, mode):
        self.mode = mode
        self.controller.reset_gesture()
        self.message = f"{mode} mode selected."

    def calibrate(self):
        if self.controller.calibrate():
            self._was_calibrating = True
            self.message = "Hold steady until calibration completes."
        else:
            self.message = "Calibration needs fresh controller data."

    def observe(self):
        if self._was_calibrating and not self.controller.calibrating:
            self.message = ("Calibration complete." if self.controller.calibrated
                            else "Calibration interrupted. Check connection.")
            self._was_calibrating = False
        if self.open and self.controller.jump:
            self.jump_tests += 1

    def change_threshold(self, value, save=True):
        value = round(max(0.10, min(0.80, value)), 2)
        if value != self.controller.detector.threshold_g:
            self.controller.set_jump_threshold(value)
        self.message = "Higher threshold needs a stronger upward lift."
        if save:
            self._save()

    def finish_edit(self):
        if self.dragging:
            self.dragging = False
            self._save()

    def handle_event(self, event):
        """Return an action for the main loop; mouse input is owned while open."""
        if not self.open:
            return None
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging:
                self.finish_edit()
            return "handled"
        if event.type == pygame.MOUSEMOTION and self.dragging:
            self.change_threshold(0.10 + (event.pos[0] - self.slider.left) / self.slider.width * 0.70,
                                  save=False)
            return "handled"
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        if self.slider.inflate(24, 24).collidepoint(event.pos):
            self.dragging = True
            self.change_threshold(0.10 + (event.pos[0] - self.slider.left) / self.slider.width * 0.70,
                                  save=False)
            return "handled"
        for action, rect in self.buttons.items():
            if not rect.collidepoint(event.pos):
                continue
            if action in {"stm32", "keyboard"}:
                self.set_mode("STM32" if action == "stm32" else "Keyboard")
                return "mode"
            if action == "close":
                return "close"
            if action == "start":
                if self.ready:
                    return "start"
                self.message = self.readiness_reason
                return "handled"
            if action in {"previous", "next"} and self.ports:
                self.selected = (self.selected + (-1 if action == "previous" else 1)) % len(self.ports)
            elif action == "refresh":
                self.refresh_ports()
            elif action == "connect":
                self.connect_selected()
            elif action == "calibrate":
                self.calibrate()
            elif action in {"light", "normal", "firm"}:
                self.change_threshold({"light": 0.18, "normal": 0.30, "firm": 0.45}[action])
            return "handled"
        return "handled"

    def draw(self, screen, font, small):
        if not self.open:
            return
        shade = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 175))
        screen.blit(shade, (0, 0))
        pygame.draw.rect(screen, (32, 39, 45), (100, 60, 900, 600), border_radius=14)

        def text(message, x, y, color=(235, 239, 242), large=False):
            screen.blit((font if large else small).render(str(message), True, color), (x, y))

        text("CONTROLLER SETTINGS", 140, 82, large=True)
        labels = {"stm32": "STM32 (primary)", "keyboard": "Keyboard (backup)",
            "close": "Close (F5)", "start": "Start / Resume", "previous": "<", "next": ">",
                  "refresh": "Refresh", "connect": "Connect / Retry", "calibrate": "Calibrate (F4)",
                  "light": "Light: 0.18 g", "normal": "Standard: 0.30 g", "firm": "Firm: 0.45 g"}
        for action, rect in self.buttons.items():
            selected = ((action == "stm32" and self.mode == "STM32") or
                        (action == "keyboard" and self.mode == "Keyboard"))
            enabled = action != "start" or self.ready
            color = (66, 113, 83) if selected else (58, 70, 78) if enabled else (43, 48, 53)
            pygame.draw.rect(screen, color, rect, border_radius=6)
            label = small.render(labels[action], True, (235, 239, 242) if enabled else (135, 140, 145))
            screen.blit(label, label.get_rect(center=rect.center))
        port = self.ports[self.selected][0] if self.ports else "No serial device"
        text(f"Selected: {port}", 205, 199)
        state = ("Sensor I2C fault" if self.controller.last_sensor_error else
                 "Calibrating..." if self.controller.calibrating else
                 "Ready" if self.controller.connected and self.controller.calibrated else
                 "Data received - calibrate" if self.controller.connected else "Waiting for valid data")
        text(f"Mode: {self.mode} | {state}", 140, 250)
        capability = ("Upward lift detection available" if self.controller.protocol_version == 2 else
                      "Legacy firmware: upward jump unavailable; upgrade firmware" if self.controller.protocol_version == 1
                      else "Waiting for device protocol")
        text(capability, 140, 280, (170, 200, 210))
        threshold = self.controller.detector.threshold_g
        text(f"Upward jump threshold: {threshold:.2f} g", 140, 315, large=True)
        pygame.draw.rect(screen, (80, 93, 101), self.slider, border_radius=6)
        thumb = self.slider.left + (threshold - 0.10) / 0.70 * self.slider.width
        pygame.draw.circle(screen, (120, 210, 145), (int(thumb), self.slider.centery), 11)
        text("0.10 g: lighter", 170, 370)
        text("0.80 g: stronger", 660, 370)
        force = self.controller.detector.vertical_g
        text(f"Live upward: {force:+.2f} g | Peak since last lift/reset: {self.controller.detector.peak_g:.2f} g",
             140, 445)
        meter = pygame.Rect(170, 480, 600, 15)
        pygame.draw.rect(screen, (58, 70, 78), meter)
        pygame.draw.rect(screen, (120, 210, 145),
                         (meter.left, meter.top, int(meter.width * max(0, min(1, force))), meter.height))
        marker = int(meter.left + meter.width * threshold)
        pygame.draw.line(screen, (240, 180, 90), (marker, 475), (marker, 500), 3)
        text(f"Try lifts here: {self.jump_tests} events | Detector: {self.controller.detector.state}", 140, 520)
        text(self.readiness_reason if not self.ready else "Start / Resume plays. Close returns to the previous pause state.",
             140, 550, (170, 180, 187))
        text((self.controller.last_error or self.message or "")[:100], 140, 585, (240, 190, 120))
        text("F3: mode | F4: calibrate | F5: settings | threshold changes save automatically", 140, 625)
