#!/usr/bin/env python3
"""Generate the two PNG icons the PCM and the toolbar require.

Stdlib only — KiCad's bundled Python has no Pillow, and adding a build-time
dependency to draw two flat images would be a poor trade. Generating them from
source also beats committing opaque binaries nobody can regenerate or adjust.

The mark is a shield with a bar across it: verification, and a thing that stays
shut.
"""
import os
import struct
import zlib

INK = (0x1F, 0x6F, 0x4B)      # green: passed
BAR = (0xF5, 0xF5, 0xF5)      # the gate bar


def _shield(x, y, size):
    """True inside a shield centred in a size x size field.

    u runs -1..1 across, v runs 0..1 down. The body is a slightly barrelled
    rectangle that tapers to a point below v=0.62.
    """
    u = (x + 0.5) / size * 2 - 1
    v = (y + 0.5) / size
    half = 0.86 - 0.34 * v * v

    # Round the top corners, so the silhouette reads as a shield rather than a
    # flat-topped pentagon.
    radius = 0.16
    if v < radius:
        half *= (1 - ((radius - v) / radius) ** 2) ** 0.5

    if v < 0.62:
        return abs(u) <= half
    taper = (1 - v) / 0.38
    return abs(u) <= half * (0.35 + 0.65 * taper)


def _rows(size):
    """Raw RGBA scanlines, each prefixed with PNG filter type 0."""
    bar_top, bar_bottom = int(size * 0.46), int(size * 0.58)
    bar_left, bar_right = size * 0.18, size * 0.82
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            if not _shield(x, y, size):
                row += b"\x00\x00\x00\x00"
            elif bar_top <= y < bar_bottom and bar_left < x < bar_right:
                row += bytes(BAR) + b"\xff"
            else:
                row += bytes(INK) + b"\xff"
        yield bytes(row)


def _chunk(tag, payload):
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def write_png(path, size):
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    body = zlib.compress(b"".join(_rows(size)), 9)
    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n"
                     + _chunk(b"IHDR", header)
                     + _chunk(b"IDAT", body)
                     + _chunk(b"IEND", b""))
    return path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    for path, size in ((os.path.join(here, "icon.png"), 64),
                       (os.path.join(here, "plugin", "icon24.png"), 24)):
        write_png(path, size)
        print(f"wrote {os.path.relpath(path, here)} ({size}x{size})")
