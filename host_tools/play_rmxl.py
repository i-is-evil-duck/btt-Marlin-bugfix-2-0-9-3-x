#!/usr/bin/env python3
"""Play an RMXL keyboard-piano file on the X and Y steppers via Marlin G-code.

Supports both notations:
    note names   B3 G4 F#4 C4 [B3E3E2] G4E3 E3[B3C3C2]
    piano keys   r o I r t t u t [r03] o0 0[r81] t [t8]

A bracketed group is a chord. A run like G4E3 (or o0) is also a chord.
The highest note of each chord (the melody) plays on X; the next note down
(secondary) plays on Y. Single notes always play on X.

Usage:
    python3 play_rmxl.py "trap queen.rmxl"
    python3 play_rmxl.py --test              # chromatic scale
    python3 play_rmxl.py --dry-run file.rmxl  # show G-code, no motor
"""
import argparse
import re
import sys
import time

from marlin import Marlin, PORT

# --- Piano-key -> MIDI note. Derived from the example you gave:
#     r=B3 t=C4 u=E4 o=G4 I=F#4 0=E3 3=E2 8=C3 1=C2
# Lowercase = white key, uppercase = that key's sharp; number row = low octaves.
KEY_MAP = {}
def _map(keys, notes):
    for k, n in zip(keys, notes):
        KEY_MAP[k] = n

_map("qwertyuiop", [53, 55, 57, 59, 60, 62, 64, 65, 67, 69])   # F3..A4
_map("QWERTYUIOP", [54, 56, 58, 60, 61, 63, 65, 66, 68, 70])   # sharps
_map("1234567890", [36, 38, 40, 41, 43, 45, 47, 48, 50, 52])   # C2..E3
_map("zxcvbnm", [48, 50, 52, 53, 55, 57, 59])
_map("s-dghj", [49, 51, 54, 56, 58])
_map(",l.;/", [60, 61, 62, 63, 64])
KEY_MAP["r"], KEY_MAP["t"], KEY_MAP["u"], KEY_MAP["o"], KEY_MAP["I"] = 59, 60, 64, 67, 66
KEY_MAP["0"], KEY_MAP["3"], KEY_MAP["8"], KEY_MAP["1"] = 52, 40, 48, 36
# shifted number row -> octave above the plain digits
_map("!@#$%^&*()", [48, 50, 52, 53, 55, 57, 59, 60, 62, 64])
_map('":<>?=', [56, 58, 61, 63, 65, 66])

NOTE_RE = re.compile(r"([A-Ga-g])([#b]?)(\d)")
PIECE_RE = re.compile(r"(\[[^\]]*\]|[^\s\[\]]+)")

NOTE_DURATION = 0.10   # seconds per note; notes chain with no gap
# Map Hz straight to steps/s. With the real driver microstepping this is well
# past pull-out, so the motor stalls and buzzes loudly at the note frequency
# (exactly the 1000-3000 steps/s range from motor_test.py).
STEPS_PER_HZ = 1
PITCH_SHIFT = 12       # semitones up
TEMPO = 1.0            # <1 faster, >1 slower


def note_name_to_midi(name, accidental, octave):
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[name.upper()]
    if accidental == "#":
        base += 1
    elif accidental == "b":
        base -= 1
    return (int(octave) + 1) * 12 + base


def parse_rmxl(text):
    """Return a list of chords (lists of MIDI notes)."""
    chords = []
    for piece in PIECE_RE.findall(text):
        body = piece[1:-1] if piece.startswith("[") else piece
        body = body.strip()
        if not body:
            continue
        notes = [note_name_to_midi(*m) for m in NOTE_RE.findall(body)]
        if notes:
            chords.append(notes)
            continue
        keys = [KEY_MAP[c] for c in body if c in KEY_MAP]
        if keys:
            chords.append(keys)
    return chords


def midi_to_hz(note):
    return 440.0 * 2 ** ((note - 69) / 12.0)


def build_commands(chords):
    cmds = []
    for i, chord in enumerate(chords):
        # Highest note is the melody -> X (the louder motor).
        # Next note down is the secondary voice -> Y.
        ordered = sorted({n + PITCH_SHIFT for n in chord})
        x = ordered[-1:]
        y = ordered[-2:-1] if len(ordered) > 1 else []

        rates = []
        for group in (x, y):
            rates.append(midi_to_hz(group[0]) * STEPS_PER_HZ if group else 0.0)
        rx, ry = rates
        duration = NOTE_DURATION * TEMPO
        parts = []
        if rx:
            parts.append(f"X{rx * duration:.3f}")
        if ry:
            parts.append(f"Y{ry * duration:.3f}")
        feed = max(rx, ry) * 60.0
        cmds.append(f"G1 {' '.join(parts)} F{feed:.0f}")
    return cmds


def play(commands, port=PORT):
    m = Marlin(port)
    setup = [
        "M211 S0",                       # soft endstops off
        "M569 S0 X Y",                   # spreadCycle: loud, not silent stealthChop
        "M906 X1200 Y1200",              # more current -> stronger vibration
        "M92 X1 Y1",                     # 1 G-code unit = 1 step
        "M203 X100000 Y100000",          # no feedrate clamp
        "M201 X100000 Y100000",
        "M204 P50000 R50000 T50000",
        "M205 J1000",                    # instant direction/frequency changes
        "M17",                           # motors on
        "G91",                           # relative
        "G92 X0 Y0",
    ]
    for c in setup:
        m.cmd(c, 0.3)
    try:
        # Stream every move back-to-back so Marlin chains them: each note is
        # held until the next one starts, with no silence in between.
        for g in commands:
            m.s.write((g + "\n").encode())
            m.read(0.002)
        m.cmd("M400", 120.0)
    finally:
        for c in ("G90", "M18", "M92 X5 Y5", "M205 J0.01",
                  "M203 X300 Y300", "M204 P3000 R3000 T3000",
                  "M201 X3000 Y3000", "M906 X800 Y800",
                  "M211 S1"):
            m.cmd(c, 0.3)
        m.close()


def build_pitch_test(start=60, count=25, seconds=2.0):
    """Ascending chromatic notes, each held for `seconds`, alternating motors."""
    cmds = []
    notes = [midi_to_hz(n + PITCH_SHIFT) * STEPS_PER_HZ for n in range(start, start + count)]
    for i, rate in enumerate(notes):
        axis = "X" if i % 2 == 0 else "Y"
        cmds.append(f"G1 {axis}{rate * seconds:.3f} F{rate * 60:.0f}")
    return cmds


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", nargs="?", help=".rmxl file to play")
    ap.add_argument("--test", action="store_true", help="chromatic scale")
    ap.add_argument("--pitch-test", action="store_true",
                    help="ascending notes, 2 seconds each")
    ap.add_argument("--dry-run", action="store_true", help="print G-code only")
    args = ap.parse_args()

    if args.pitch_test:
        cmds = build_pitch_test()
    elif args.test:
        cmds = build_commands([[n] for n in range(60, 73)])
    elif args.file:
        with open(args.file, encoding="utf-8", errors="replace") as f:
            cmds = build_commands(parse_rmxl(f.read()))
    else:
        ap.error("give a file, --test or --pitch-test")
    print(f"{len(cmds)} moves", file=sys.stderr)
    if args.dry_run:
        print("\n".join(cmds[:20]))
        if len(cmds) > 20:
            print(f"... {len(cmds) - 20} more")
    else:
        play(cmds)


if __name__ == "__main__":
    main()
