"""Small, validated local player settings, saved atomically."""

import json
import math
from pathlib import Path
import tempfile

if __package__:
    from .controller.upward_jump import UpwardJumpDetector
else:
    from controller.upward_jump import UpwardJumpDetector

SETTINGS_PATH = Path(__file__).with_name("user_settings.json")


def load_settings(path=None):
    result = {"jump_threshold_g": UpwardJumpDetector.DEFAULT_THRESHOLD, "port": ""}
    try:
        value = json.loads(Path(path or SETTINGS_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return result
    if not isinstance(value, dict):
        return result
    threshold = value.get("jump_threshold_g")
    if (type(threshold) in (int, float) and math.isfinite(threshold)
            and UpwardJumpDetector.MIN_THRESHOLD <= threshold <= UpwardJumpDetector.MAX_THRESHOLD):
        result["jump_threshold_g"] = float(threshold)
    port = value.get("port")
    if isinstance(port, str) and len(port) <= 128:
        result["port"] = port
    return result


def save_settings(value, path=None):
    path = Path(path or SETTINGS_PATH)
    threshold = value["jump_threshold_g"]
    if (type(threshold) not in (int, float) or not math.isfinite(threshold)
            or not UpwardJumpDetector.MIN_THRESHOLD <= threshold <= UpwardJumpDetector.MAX_THRESHOLD):
        raise ValueError("Invalid jump threshold")
    payload = {"jump_threshold_g": threshold, "port": str(value.get("port", ""))}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
