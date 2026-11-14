"""QR codes for the guests' address, as SVG."""

# Copyright (C) 2026 Nadav Har'El
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import functools
import io

import segno


@functools.lru_cache(maxsize=16)
def svg(url: str, dark: str = "#000") -> str:
    # Error correction "M": still scans with a smudge or a glare on the screen,
    # without making the code so dense that it fails from across a room.
    code = segno.make_qr(url, error="m")
    out = io.BytesIO()
    # No width or height: the page sizes it, and it scales without blurring.
    code.save(out, kind="svg", dark=dark, light=None, border=2,
              xmldecl=False, svgns=True, omitsize=True)
    return out.getvalue().decode()
