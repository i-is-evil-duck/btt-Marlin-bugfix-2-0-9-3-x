#!/usr/bin/env python3
"""Continuous speed ramp on motor X, with live speed readout and pause.

Press 't' (or space) to pause/resume the ramp. Press 'q' to stop early.
The current speed is shown live in the terminal.

    python3 motor_test.py
    python3 motor_test.py --start 200 --end 4000 --step 25 --seconds 1.5
    python3 motor_test.py --dry-run
"""
import argparse
import os
import sys
import threading
import time
from collections import deque

from marlin import Marlin, PORT

STEPS_PER_REV = 200   # X now runs full-step after the firmware rebuild


class Keys:
    """Read keypresses in a background thread so none are ever missed."""

    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.old = None
        self.queue = deque()
        self.running = True
        if sys.stdin.isatty():
            import termios
            self.old = termios.tcgetattr(self.fd)
            raw = termios.tcgetattr(self.fd)
            raw[3] &= ~(termios.ICANON | termios.ECHO | termios.ISIG)
            raw[6][termios.VMIN] = 1
            raw[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSAFLUSH, raw)
            self.thread = threading.Thread(target=self._read, daemon=True)
            self.thread.start()
        else:
            self.thread = None

    def _read(self):
        while self.running:
            try:
                ch = os.read(self.fd, 1)
            except OSError:
                return
            if ch:
                self.queue.append(ch.decode(errors="ignore").lower())

    def poll(self):
        return self.queue.popleft() if self.queue else None

    def close(self):
        self.running = False
        if self.old is not None:
            import termios
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)


def show(rate, elapsed, total, paused):
    rpm = rate * 60.0 / STEPS_PER_REV
    state = "PAUSED" if paused else "running"
    print(f"\rX {rate:>6} steps/s | {rpm:>7.1f} RPM | "
          f"{elapsed:>6.1f}/{total:<6.1f}s | {state:<6} | "
          f"t/space=pause q=quit", end="", flush=True)


def run(start, end, step, seconds, accel, port=PORT, dry=False):
    # F0 isn't a valid feedrate, so begin at 1 step/s (0.3 RPM ≈ 0 RPM).
    rates = list(range(max(start, 1), end + 1, step))
    total = len(rates) * seconds
    print(f"{'steps/s':>9} {'~RPM':>8} {'F(mm/min)':>11}")
    for r in rates:
        print(f"{r:>9} {r * 60.0 / STEPS_PER_REV:>8.1f} {r * 60:>11}")
    print(f"\n{len(rates)} steps, ~{total:.0f}s total, accel {accel} steps/s^2")
    if dry:
        return

    m = Marlin(port)
    keys = Keys()
    setup = [
        "M211 S0",
        "M569 S1 X",            # stealthChop (quieter, reaches higher RPM)
        "M906 X1200",
        "M92 X1",               # 1 unit = 1 step
        "M203 X100000",
        f"M201 X{accel}",
        f"M204 P{accel} R{accel} T{accel}",
        "M205 J1000",           # smooth handoff between speeds
        "M17",
        "G91",
        "G92 X0",
    ]
    for c in setup:
        m.cmd(c, 0.3)
    m.read(0.2)  # drain stale replies

    def queue_from(index):
        # Send every remaining speed up front. Marlin's lookahead sees the
        # whole chain, so it goes straight from one speed to the next with
        # no deceleration at each step.
        for r in rates[index:]:
            m.s.write(f"G1 X{r * seconds:.3f} F{r * 60}\n".encode())
            m.read(0.002)

    def stop():
        m.cmd("M410", 0.5)   # quickstop: abort all planned moves
        m.cmd("M400", 2.0)   # let the motors settle
        m.cmd("M18", 0.3)    # release them so it definitely stops

    queue_from(0)
    start_time = time.monotonic()
    pause_start = None

    try:
        while True:
            now = time.monotonic()
            effective = pause_start if pause_start is not None else now
            elapsed = min(effective - start_time, total)
            display_idx = min(int(elapsed / seconds), len(rates) - 1) if seconds else 0
            rate = rates[display_idx]

            key = keys.poll()
            if key in ("t", "p", " ", "q"):
                was_paused = pause_start is not None
                frozen_rate = rate
                if not was_paused:
                    pause_start = now   # freeze the readout at this instant
                stop()
                if key == "q":
                    print("\nstopped early")
                    break
                if not was_paused:
                    print(f"\n*** PAUSED at {frozen_rate} steps/s "
                          f"({frozen_rate * 60.0 / STEPS_PER_REV:.1f} RPM) "
                          f"- press t to resume ***")
                else:
                    # Shift the timeline so the readout resumes at the same
                    # speed, then re-queue from that speed onward.
                    start_time += time.monotonic() - pause_start
                    pause_start = None
                    m.cmd("M17", 0.3)   # re-enable motors
                    queue_from(display_idx)
                    print(f"\n*** RESUMING at {frozen_rate} steps/s ***")
                continue

            show(rate, elapsed, total, pause_start is not None)

            if elapsed >= total and pause_start is None:
                m.cmd("M400", 30.0)   # wait for the last queued move
                break

            time.sleep(0.02)
    finally:
        keys.close()
        for c in ("G90", "M18", "M92 X5", "M205 J0.01",
                  "M203 X300", "M204 P3000 R3000 T3000",
                  "M201 X3000", "M906 X800", "M211 S1"):
            m.cmd(c, 0.3)
        m.close()
        print()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=0,
                    help="starting steps/s (0 starts at ~0 RPM)")
    ap.add_argument("--end", type=int, default=3000)
    ap.add_argument("--step", type=int, default=50)
    ap.add_argument("--seconds", type=float, default=1.0)
    ap.add_argument("--accel", type=int, default=10000,
                    help="steps/s^2 - lower = slower, smoother ramp")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.step <= 0:
        ap.error("--step must be positive")
    run(args.start, args.end, args.step, args.seconds, args.accel,
        dry=args.dry_run)


if __name__ == "__main__":
    main()
