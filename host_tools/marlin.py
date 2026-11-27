#!/usr/bin/env python3
"""Small helper for talking to a Marlin board over USB serial."""
import sys
import time
import serial

PORT = "/dev/cu.usbmodem3666376733311"
BAUD = 115200


class Marlin:
    def __init__(self, port=PORT, baud=BAUD):
        self.s = serial.Serial(port, baud, timeout=0.3)
        time.sleep(0.3)
        self.s.reset_input_buffer()

    def read(self, seconds=1.0):
        end = time.time() + seconds
        out = b""
        self.s.timeout = 0
        while time.time() < end:
            waiting = self.s.in_waiting
            if waiting:
                out += self.s.read(waiting)
                if b"ok" in out or b"echo:Unknown" in out or b"Error:" in out:
                    break
            else:
                time.sleep(0.005)
        return out.decode(errors="replace")

    def cmd(self, line, seconds=1.0):
        self.s.write((line + "\n").encode())
        return self.read(seconds)

    def close(self):
        self.s.close()

    def spin360(self, feedrate=18000, accel=1000):
        """Spin X one full revolution without stalling.

        15 deg = 26.667 mm at M92 X5 with 1/16 microstepping, so
        360 deg = 640 mm = 3200 microsteps. G1's F is in mm/min, so
        F18000 = 300 mm/s. Accel is deliberately gentle: at 1000 mm/s^2
        the ramp to 300 mm/s takes 0.3 s over 45 mm, so the rotor has
        time to get moving instead of stalling on the first few steps.
        """
        for c in (
            "M92 X5",
            f"M203 X{feedrate // 60}",
            f"M201 X{accel}",
            f"M204 P{accel} R{accel} T{accel}",
            "M17",
            "G91",
        ):
            self.cmd(c, 0.2)
        self.cmd(f"G1 X640 F{feedrate}", 0.2)
        self.cmd("M400", 20.0)  # block until the move actually finishes
        position = self.cmd("M114", 0.5)
        for c in (
            "M203 X300",
            "M201 X3000",
            "M204 P3000 R3000 T3000",
            "G90",
            "M18",
        ):
            self.cmd(c, 0.2)
        return position


if __name__ == "__main__":
    m = Marlin()
    if "--spin" in sys.argv:
        print(m.spin360(), end="")
    else:
        for line in sys.argv[1:]:
            print(f">>> {line}")
            print(m.cmd(line))
    m.close()
