# BTT Octopus Pro — Marlin `bugfix-2.0.9.3.x` (custom)

Private fork of the BigTreeTech Octopus V1.0 Marlin `bugfix-2.0.9.3.x` release,
configured for an **Octopus Pro v1.1 / STM32H723ZE** board with **eight TMC2209
UART motor drivers** and no extruder.

The upstream Marlin README is kept in [`README.upstream.md`](README.upstream.md).

## Hardware / wiring assumptions

- Board: BigTreeTech Octopus Pro v1.1, STM32H723ZE
- Drivers: TMC2209 in **UART** mode on all enabled axes (SPI is not used)
- Enabled axes: `X`, `Y`, `Z`, `I`, `J`, `K`, `U`, `V`
  - In G-code, `I/J/K` appear as `A/B/C`; `U/V` appear as `U/V`
  - `V` is the 8th driver supplied through `BTT_MOTOR_EXPANSION`
- Extruder: disabled (`EXTRUDERS 0`)
- USB serial: `/dev/cu.usbmodem3666376733311`, `115200` baud
  - Edit `host_tools/marlin.py` if the macOS device name changes

## What is customized

### Driver configuration

- `X/Y/Z/I/J/K/U/V_DRIVER_TYPE TMC2209`
- `BTT_MOTOR_EXPANSION` enabled for the 8th axis
- `INTERPOLATE false` globally
- Every enabled TMC axis uses `*_MICROSTEPS 0`:
  - **0 = full step**, with no 256x interpolation
  - `X_INTERPOLATE false` makes the full-step setting explicit
- stealthChop is enabled for quiet operation; `motor_test.py` also sends
  `M569 S1 X` during setup
- `EMERGENCY_PARSER` is enabled so `M410` quick-stop is processed immediately
  even when the whole ramp has been pre-queued into Marlin's lookahead buffer

### Eight-axis arrays

Marlin requires matching array lengths for all eight linear axes. The following
were widened to eight elements:

- `DEFAULT_AXIS_STEPS_PER_UNIT`
- `DEFAULT_MAX_FEEDRATE`
- `DEFAULT_MAX_ACCELERATION`
- `HOMING_BUMP_MM`
- `HOMING_BUMP_DIVISOR`
- `AXIS_RELATIVE_MODES`
- `HOMING_FEEDRATE_MM_M`
- `MANUAL_FEEDRATE`

Extra-axis limits, homing directions, enable polarity, direction inversions,
endstop pins and endstop plugs are also defined for `I/J/K/U/V`. The 8th
driver uses the `E4` pin slot, which Marlin maps to the `V` axis when
`EXTRUDERS 0`.

### Source patches carried in this fork

These patches are needed to make this BTT 2.0.9.3 release build with eight axes
on this toolchain:

- `Marlin/src/core/types.h`: fix 2.0.9.3 V-axis `set()` parameter names and
  scalar operator parameter shadowing (`pu`, `pv`, `const float &v`, etc.).
- `buildroot/share/PlatformIO/scripts/marlin.py`: iterate over a copy of
  `env['CPPDEFINES']` to avoid `RuntimeError: deque mutated during iteration`.
- `Marlin/src/module/probe.h`: expand the probe offset initializer to eight
  axis elements.
- `Marlin/src/HAL/STM32/sdio.cpp`: declare the variant-provided `PinMap_SD`
  table, which the pinned Arduino core header no longer declares.
- `buildroot/share/PlatformIO/`: add the Octopus Pro `marlin_STM32H723ZE.json`
  board and `MARLIN_H723ZE` variant from the newer Marlin tree. This restores
  the known-good Octopus Pro pin map and 550 MHz CPU setting.
- `ini/stm32h7.ini`: pin the STM32H7 build chain:
  - `platform = ststm32@15.4.1`
  - `framework = framework-arduinoststm32@~4.20600.231001`
  - `board = marlin_STM32H723ZE` (the PlatformIO environment name remains
    `STM32H723Zx_btt`)

## Build

A Python virtual environment is recommended so the pinned PlatformIO packages
do not affect other projects:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install platformio

pio run -e STM32H723Zx_btt
```

The binary is written to:

```text
.pio/build/STM32H723Zx_btt/firmware.bin
```

`.pio/` is ignored by Git.

## Flash

1. Copy `firmware.bin` to the root of a FAT32 SD card.
2. Power off the board, insert the card, and power it back on.
3. Marlin flashes the file and renames it `FIRMWARE.CUR`.

## Verify after boot

Connect at `115200` baud and send:

```gcode
M122
M569
```

Expected notes:

- `M122` should report the installed TMC2209 drivers as OK.
- The 8th expansion driver `V` may report `Error: All LOW` if no driver is
  physically installed in that slot.
- `M569` should show stealthChop enabled for the enabled axes.

## Host tools

The helper scripts used to exercise the motors live in `host_tools/`.

```sh
cd host_tools
python3 motor_test.py --start 0 --end 3000 --step 50 --seconds 1
```

`motor_test.py` behavior:

- Starts at approximately 0 RPM (clamped to 1 step/s; 0 is not a valid feedrate)
- Increases speed in steps with no deceleration at each step by pre-queueing
  the full move chain into Marlin's lookahead
- Shows the current speed live in steps/s and RPM
- `t` or space pauses/resumes; `q` stops early

To play `.rmxl` music files:

```sh
cd host_tools
python3 play_rmxl.py ../path/to/song.rmxl
```

Both scripts require `pyserial`:

```sh
pip install pyserial
```

## License

Marlin is GPL-3.0 licensed; see [`LICENSE`](LICENSE).
