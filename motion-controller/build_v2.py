"""Build v2 firmware using an existing GNU Tools for STM32 installation.

Example (repository root):
python motion-controller/build_v2.py --toolchain path/to/tools/bin/arm-none-eabi-gcc.exe
HAL/USB dependencies are read from the preserved original project ZIP. Current
Core sources and linker script always override that package's application files.
No IDE project regeneration, installation, flashing, or original ELF overwrite.
"""

import argparse
from pathlib import Path
import shutil
import subprocess
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", required=True, type=Path)
    args = parser.parse_args()
    gcc = args.toolchain.resolve()
    root = Path(__file__).resolve().parent
    work = root.parent / "tmp" / "firmware-v2"
    work.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(root / "releases" / "motion_controller_project.zip") as archive:
        for entry in archive.infolist():
            if not (work / entry.filename).resolve().is_relative_to(work.resolve()):
                raise ValueError("Unsafe source archive path")
        archive.extractall(work)
    for path in (root / "Core").rglob("*"):
        if path.is_file():
            target = work / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    shutil.copy2(root / "STM32F103C8TX_FLASH.ld", work)
    includes = ["Core/Inc", "Drivers/STM32F1xx_HAL_Driver/Inc",
                "Drivers/STM32F1xx_HAL_Driver/Inc/Legacy", "Drivers/CMSIS/Include",
                "Drivers/CMSIS/Device/ST/STM32F1xx/Include",
                "Middlewares/ST/STM32_USB_Device_Library/Core/Inc",
                "Middlewares/ST/STM32_USB_Device_Library/Class/CDC/Inc"]
    flags = ["-mcpu=cortex-m3", "-mthumb", "-mfloat-abi=soft", "-Os", "-g3",
             "-ffunction-sections", "-fdata-sections", "-Wall", "-Wextra",
             "-DUSE_HAL_DRIVER", "-DSTM32F103xB", "--specs=nano.specs"]
    for directory in includes:
        flags.extend(["-I", directory])
    sources = sorted(p for directory in ("Core", "Drivers", "Middlewares")
                     for p in (work / directory).rglob("*") if p.suffix in {".c", ".s"})
    objects = []
    for index, path in enumerate(sources):
        output = f"obj_{index}.o"
        command = [str(gcc), *flags, "-c", path.relative_to(work).as_posix(), "-o", output]
        if path.suffix == ".c":
            command.append("-std=gnu11")
        subprocess.run(command, cwd=work, check=True)
        objects.append(output)
    elf = "motion_controller_v2.elf"
    subprocess.run([str(gcc), *flags, *objects, "-o", elf,
                    "-fno-use-linker-plugin",
                    "-TSTM32F103C8TX_FLASH.ld", "--specs=nosys.specs",
                    "-Wl,--gc-sections", "-Wl,-Map,motion_controller_v2.map",
                    "-Wl,--start-group", "-lc", "-lm", "-Wl,--end-group"], cwd=work, check=True)
    binutils = gcc.parent
    subprocess.run([str(binutils / "arm-none-eabi-size.exe"), elf], cwd=work, check=True)
    subprocess.run([str(binutils / "arm-none-eabi-objcopy.exe"), "-O", "ihex", elf,
                    "motion_controller_v2.hex"], cwd=work, check=True)
    for filename in (elf, "motion_controller_v2.hex"):
        destination = root / "releases" / filename
        shutil.copy2(work / filename, destination)
        print(destination)


if __name__ == "__main__":
    main()
