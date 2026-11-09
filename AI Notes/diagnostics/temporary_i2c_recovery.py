"""Read-only by default. --apply requires explicit approval for peripheral writes.

No Flash writes or MCU reset. The applied sequence halts once, uses PB8/PB9
open-drain clocks/STOP, resets I2C1 only, restores configuration, then resumes.
GPIO levels are logged for post-sequence validation; a low release is failure,
not a reason to drive the bus high. Reference: ST ES096 section 2.8.7.
"""

import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import uuid


REGISTERS = {
    "GPIO_CRH": 0x40010C04, "GPIO_ODR": 0x40010C0C, "GPIO_IDR": 0x40010C08,
    "CR1": 0x40005400, "CR2": 0x40005404, "OAR1": 0x40005408,
    "OAR2": 0x4000540C, "CCR": 0x4000541C, "TRISE": 0x40005420,
    "SR2": 0x40005418, "REMAP": 0x40010004, "DEVICE_ID": 0xE0042000,
}
WRITABLE = {REGISTERS[name] for name in
            ("GPIO_CRH", "GPIO_ODR", "CR1", "CR2", "OAR1", "OAR2", "CCR", "TRISE")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Approved peripheral recovery; default is reads only")
    mode.add_argument("--plan", action="store_true", help="Read and save the proposed command list without writes")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    folder = Path(__file__).resolve().parent
    programmer = (root / "tmp/programmer").resolve()
    query = ctypes.windll.kernel32.QueryDosDeviceW
    query.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
    query.restype = ctypes.c_ulong
    buffer = ctypes.create_unicode_buffer(32768)
    if query("R:", buffer, len(buffer)):
        raise RuntimeError("R: is already in use; no changes made")
    subprocess.run(["subst", "R:", str(programmer)], check=True)
    tag = uuid.uuid4().hex[:8]
    base = [r"R:\bin\STM32_Programmer_CLI.exe", "-c", "port=SWD", "mode=HOTPLUG",
            "freq=950", "sn=37FF71064E57343634031343"]

    def run(options, label):
        result = subprocess.run(base + options, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=30)
        output = result.stdout.decode("utf-8", errors="replace")
        (folder / f"i2c_{tag}_{label}.log").write_text(output, encoding="utf-8")
        if result.returncode or re.search(r"(?m)^\s*Error\b", output):
            raise RuntimeError(f"CLI failed during {label}; inspect its saved log")
        return output

    def write(options, name, value):
        address = REGISTERS[name]
        assert address in WRITABLE and 0 <= value <= 0xFFFFFFFF
        options.extend(["-w32", hex(address), hex(value)])

    try:
        reads = ["-score"]
        for address in REGISTERS.values():
            reads += ["-r32", hex(address), "4"]
        output = run(reads, "snapshot")
        values = {int(a, 16): int(v, 16) for a, v in
                  re.findall(r"0x([0-9A-Fa-f]{8})\s*:\s*([0-9A-Fa-f]{8})", output)}
        if any(address not in values for address in REGISTERS.values()):
            raise RuntimeError("Incomplete snapshot; no writes made")
        saved = {name: values[address] for name, address in REGISTERS.items()}
        (folder / f"i2c_{tag}_snapshot.json").write_text(
            json.dumps(saved, indent=2) + "\n", encoding="utf-8")
        print("SNAPSHOT", json.dumps({k: hex(v) for k, v in saved.items()}), flush=True)
        if not args.apply and not args.plan:
            print("READ_ONLY: no halt, peripheral writes, MCU reset or Flash writes")
            return
        if saved["DEVICE_ID"] & 0xFFF != 0x410 or not saved["REMAP"] & 2:
            raise RuntimeError("Unexpected target or I2C pin mapping; no writes made")
        if saved["GPIO_CRH"] & 0xFF != 0xFF or not saved["CR1"] & 1:
            raise RuntimeError("Target not in expected configured I2C mode; no writes made")

        # Preserve configuration; START/STOP/SWRST are transient commands.
        enabled_cr1 = saved["CR1"] & ~0x8300
        disabled_cr1 = enabled_cr1 & ~1
        release = saved["GPIO_ODR"] | 0x300

        def restoration(options, reset_i2c):
            # SWRST clears ACK and other control bits. Clear reset with zero
            # first; carrying ACK into SWRST causes CLI readback verification
            # to fail even when the peripheral accepted the reset command.
            write(options, "CR1", 0)
            write(options, "GPIO_CRH", saved["GPIO_CRH"])
            write(options, "GPIO_ODR", saved["GPIO_ODR"])
            if reset_i2c:
                write(options, "CR1", 0x8000)
                write(options, "CR1", 0)
            for name in ("CR2", "OAR1", "OAR2", "CCR", "TRISE"):
                write(options, name, saved[name])
            write(options, "CR1", enabled_cr1 & ~0x400)
            write(options, "CR1", enabled_cr1)

        options = ["-halt", "-score"]
        labels = []

        def sample(label):
            labels.append(label)
            options.extend(["-r32", hex(REGISTERS["GPIO_IDR"]), "4"])

        write(options, "CR1", disabled_cr1)
        write(options, "GPIO_ODR", release)
        write(options, "GPIO_CRH", (saved["GPIO_CRH"] & ~0xFF) | 0x77)
        sample("released_before_clocks")
        for pulse in range(9):
            write(options, "GPIO_ODR", release & ~0x100)
            write(options, "GPIO_ODR", release)
            sample(f"clock_{pulse + 1}_released")
        write(options, "GPIO_ODR", release & ~0x200)
        sample("sda_low")
        write(options, "GPIO_ODR", release & ~0x300)
        sample("both_low")
        write(options, "GPIO_ODR", release & ~0x200)
        sample("scl_released")
        write(options, "GPIO_ODR", release)
        sample("both_released")
        restoration(options, reset_i2c=True)
        sample("restored")
        options += ["-r32", hex(REGISTERS["SR2"]), "4", "-run", "-score"]
        if args.plan:
            plan = {"mode": "plan_only_no_register_writes", "snapshot": saved,
                    "gpio_sample_labels": labels, "command_arguments": options,
                    "write_count": options.count("-w32"),
                    "flash_writes": False, "mcu_reset": False}
            plan_path = folder / f"i2c_{tag}_plan.json"
            plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            print("PLAN_ONLY", plan_path.name, "WRITES_PLANNED", plan["write_count"],
                  "NO_HALT_OR_REGISTER_WRITES_EXECUTED")
            return
        finished = False
        try:
            output = run(options, "approved_recovery")
            levels = re.findall(r"0x40010C08\s*:\s*([0-9A-Fa-f]{8})", output)
            if len(levels) != len(labels) or "Core is running" not in output:
                raise RuntimeError("Incomplete recovery output or resume not confirmed")
            result = [{"step": name, "scl": (int(v, 16) >> 8) & 1,
                       "sda": (int(v, 16) >> 9) & 1} for name, v in zip(labels, levels)]
            (folder / f"i2c_{tag}_levels.json").write_text(
                json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print("LEVELS", json.dumps(result), flush=True)
            print("CONFIGURATION_RESTORED_AND_CPU_RUNNING; verify actual sensor packets separately")
            finished = True
        finally:
            if not finished:
                fallback = ["-halt"]
                restoration(fallback, reset_i2c=False)
                fallback += ["-run", "-score"]
                run(fallback, "restore_after_error")
    finally:
        buffer = ctypes.create_unicode_buffer(32768)
        if (query("R:", buffer, len(buffer)) and
                os.path.normcase(buffer.value) == os.path.normcase("\\??\\" + str(programmer))):
            subprocess.run(["subst", "R:", "/D"], check=True)


if __name__ == "__main__":
    main()
