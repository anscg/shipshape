"""Render Hack Club Make shipping labels (4x2", H30C-Lite).

Geometry is measured off the designer's original artwork, expressed in the
frame SVG's own user units (799 x 399 == 4in x 2in).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

import qrcode
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
FRAME_SVG = os.path.join(ASSETS, "frame.svg")
FRAME_PNG = os.path.join(ASSETS, "frame@600.png")
FONT_PATH = os.path.join(ASSETS, "Geist-Regular.ttf")

# --- design units -----------------------------------------------------------
# The frame SVG's viewBox. 799 units wide == 4in, 399 units tall == 2in.
DESIGN_W = 799.0
DESIGN_H = 399.0

LABEL_W_IN = 4.0
LABEL_H_IN = 2.0

# Address block, measured from the original PDF at 600dpi and divided by 8.333.
TEXT_X = 57.0
BASELINE_1 = 134.167
LINE_PITCH = 39.0
FONT_SIZE = 30.086
N_LINES = 5

# The QR sits beside lines 1-2, so those wrap earlier than the rest.
QR_X = 636.03
QR_Y = 48.0
QR_SIZE = 107.05

# Right-hand limit for each address line before it gets shrunk to fit.
LINE_MAX_X = (470.0, 470.0, 745.0, 745.0, 745.0)

# Placeholder only: a fictional name and a number from Ofcom's reserved
# drama range, so nothing real ships on a test label.
DEFAULT_LINES = [
    "Fiona Hackworth",
    "+44 20 7946 0142",
    "88 Analytical Engine Way",
    "Marylebone, London",
    "W1U 4RW",
]
DEFAULT_QR = "https://hackclub.com"


@dataclass
class Label:
    lines: list = field(default_factory=lambda: list(DEFAULT_LINES))
    qr_data: str = DEFAULT_QR

    def normalised(self):
        out = [(self.lines[i] if i < len(self.lines) else "") for i in range(N_LINES)]
        return [(s or "").strip() for s in out]


def _frame(width_px: int, height_px: int) -> Image.Image:
    """The static artwork at the requested pixel size.

    Re-rasterised from the SVG when librsvg is around (crisper at any size),
    otherwise resampled from the bundled 600dpi PNG.
    """
    rsvg = shutil.which("rsvg-convert")
    if rsvg and os.path.exists(FRAME_SVG):
        try:
            out = subprocess.run(
                [rsvg, "-w", str(width_px), "-h", str(height_px), FRAME_SVG],
                check=True, capture_output=True,
            ).stdout
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
                fh.write(out)
                tmp = fh.name
            try:
                img = Image.open(tmp).convert("RGB")
                return img.copy()
            finally:
                os.unlink(tmp)
        except (subprocess.CalledProcessError, OSError):
            pass
    img = Image.open(FRAME_PNG).convert("RGB")
    if img.size != (width_px, height_px):
        img = img.resize((width_px, height_px), Image.LANCZOS)
    return img


def _fit_font(text: str, max_width_px: float, base_size_px: float):
    """Largest size <= base that keeps `text` inside max_width_px."""
    size = max(1, int(round(base_size_px)))
    font = ImageFont.truetype(FONT_PATH, size)
    if not text or font.getlength(text) <= max_width_px:
        return font
    while size > 4:
        size -= 1
        font = ImageFont.truetype(FONT_PATH, size)
        if font.getlength(text) <= max_width_px:
            break
    return font


def _qr_image(data: str, target_px: float):
    """A pixel-snapped QR bitmap, so modules stay crisp on a thermal head."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=0,
    )
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)

    module_px = max(1, int(round(target_px / n)))
    side = module_px * n

    img = Image.new("1", (n, n), 1)
    px = img.load()
    for y, row in enumerate(matrix):
        for x, on in enumerate(row):
            if on:
                px[x, y] = 0
    return img.resize((side, side), Image.NEAREST), side


def render(label: Label, dpi: int = 300, mono: bool = False) -> Image.Image:
    width_px = int(round(LABEL_W_IN * dpi))
    height_px = int(round(LABEL_H_IN * dpi))
    sx = width_px / DESIGN_W
    sy = height_px / DESIGN_H

    img = _frame(width_px, height_px)
    draw = ImageDraw.Draw(img)

    lines = label.normalised()
    base_size_px = FONT_SIZE * sx
    for i, text in enumerate(lines):
        if not text:
            continue
        max_width_px = (LINE_MAX_X[i] - TEXT_X) * sx
        font = _fit_font(text, max_width_px, base_size_px)
        x = TEXT_X * sx
        y = (BASELINE_1 + i * LINE_PITCH) * sy
        draw.text((x, y), text, font=font, fill=(0, 0, 0), anchor="ls")

    data = (label.qr_data or "").strip()
    if data:
        qr_img, side = _qr_image(data, QR_SIZE * sx)
        # Centre the snapped bitmap inside the designer's QR box.
        nominal = QR_SIZE * sx
        x = int(round(QR_X * sx + (nominal - side) / 2))
        y = int(round(QR_Y * sy + (QR_SIZE * sy - side) / 2))
        img.paste(qr_img.convert("RGB"), (x, y))

    if mono:
        # A thermal head only fires or doesn't, so hard-threshold rather than
        # dither: this is literally the dot pattern that lands on the label.
        img = img.convert("L").point(lambda v: 0 if v < 128 else 255, mode="1")

    return img


def save_pdf(img: Image.Image, path: str, dpi: int) -> str:
    """Write a PDF whose page is exactly 4x2in, so the printer never rescales."""
    # Mode "1" is kept as-is: a 1-bit page prints the exact dot pattern.
    out = img if img.mode == "1" else img.convert("RGB")
    out.save(path, "PDF", resolution=float(dpi),
             title="Hack Club Make shipping label")
    return path


def list_printers():
    try:
        out = subprocess.run(
            ["lpstat", "-p"], capture_output=True, text=True, check=False
        ).stdout
    except OSError:
        return []
    names = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "printer":
            names.append(parts[1])
    return names


def printer_resolution(name: str):
    """The queue's native dpi from its PPD, or None if the driver doesn't say.

    Matters because a 1-bit page is only exact when its resolution matches the
    head: at any other resolution the driver rescales and the dots smear.
    """
    ppd = f"/etc/cups/ppd/{name}.ppd"
    try:
        with open(ppd, "r", errors="ignore") as fh:
            for line in fh:
                if line.startswith("*DefaultResolution:"):
                    value = line.split(":", 1)[1].strip().strip('"')
                    digits = "".join(c for c in value.split("x")[0] if c.isdigit())
                    return int(digits) if digits else None
    except OSError:
        return None
    return None


def default_printer():
    try:
        out = subprocess.run(
            ["lpstat", "-d"], capture_output=True, text=True, check=False
        ).stdout
    except OSError:
        return None
    if ":" in out:
        return out.split(":", 1)[1].strip() or None
    return None


def print_label(label: Label, printer: str, dpi: int = 203, copies: int = 1,
                media: str = "Custom.4x2in", mono: bool = True) -> str:
    """Send the label to CUPS. Returns the `lp` output."""
    img = render(label, dpi=dpi, mono=mono)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
        path = fh.name
    save_pdf(img, path, dpi)
    # No fit-to-page: the page is already exactly 4x2in, and letting the driver
    # rescale would knock a 1-bit render off the printer's dot grid.
    cmd = ["lp", "-d", printer, "-n", str(max(1, copies)),
           "-o", f"media={media}", path]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return (res.stdout or "").strip() or "Sent to printer."
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
