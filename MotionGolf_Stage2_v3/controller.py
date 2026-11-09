"""Stage 2 adapter for the existing, hardware-tested controller implementation.

Both game versions share one parser, calibration/detector and player settings.
Roll/pitch are normalized inputs; jump is one event per update, not a held bit.
"""

from pathlib import Path
import sys

# Support both `python main.py` from this folder and `python -m ...` at repo root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from MotionGolf_Stage1_v4.controller import ControllerConfig, SerialController, parse_packet
from MotionGolf_Stage1_v4.controller_panel import ControllerPanel


class STM32SerialController(SerialController):
    """Keep the Stage 2 class/lifecycle names with the verified input contract."""

    def __init__(self, config=None, **options):
        super().__init__(config or ControllerConfig(invert_pitch=True), **options)

    @property
    def port_name(self):
        return self.port

    @property
    def serial_port(self):
        return self._serial

    @staticmethod
    def get_available_ports():
        return [{"device": port, "description": description}
                for port, description in SerialController.available_ports()]

    def disconnect(self):
        self.close()


if __name__ == "__main__":
    print("Available ports:", STM32SerialController.get_available_ports())
    print("Parser example:", parse_packet("ROLL:-12.3,PITCH:4.5,JUMP:0"))
