"""Provider-independent image decoding.

Decodes image bytes into the internal `Image` (RGB pixel grid) using ONLY the
Python standard library: a full PNG decoder (8-bit, color types 0/2/3/4/6, all
filter types) and a BMP decoder (24/32-bit, uncompressed). Optionally, if
Pillow is installed, it is used as a fallback for formats PNG/BMP cannot cover
(JPEG, GIF, WebP, ...).

The decoders are synchronous and deterministic, so the vision subsystem has zero
required third-party dependencies.
"""

from __future__ import annotations

import struct
import zlib

from app.vision.errors import VisionDecodeError
from app.vision.models import Image

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _blend(r: int, g: int, b: int, a: int) -> tuple[int, int, int]:
    """Composite an RGBA pixel over a white background."""
    factor = a / 255.0
    return (
        int(r + (255 - r) * factor),
        int(g + (255 - g) * factor),
        int(b + (255 - b) * factor),
    )


def _paeth(a: int, b: int, c: int) -> int:
    """PNG Paeth predictor."""
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(line: bytearray, prev: bytearray, filter_type: int, bpp: int) -> None:
    """Reverse a PNG scanline filter in place."""
    for i in range(len(line)):
        raw = line[i]
        left = line[i - bpp] if i >= bpp else 0
        up = prev[i]
        up_left = prev[i - bpp] if i >= bpp else 0
        if filter_type == 0:
            value = raw
        elif filter_type == 1:
            value = raw + left
        elif filter_type == 2:
            value = raw + up
        elif filter_type == 3:
            value = raw + (left + up) // 2
        elif filter_type == 4:
            value = raw + _paeth(left, up, up_left)
        else:
            msg = f"Unsupported PNG filter: {filter_type}"
            raise VisionDecodeError(msg)
        line[i] = value & 0xFF


def _decode_png(data: bytes) -> Image:
    """Decode an 8-bit, non-interlaced PNG."""
    if not data.startswith(_PNG_SIGNATURE):
        msg = "Not a PNG image"
        raise VisionDecodeError(msg)

    width = height = bit_depth = color_type = None
    interlace = 0
    palette: list[tuple[int, int, int]] = []
    idat = bytearray()

    pos = 8
    total = len(data)
    while pos + 8 <= total:
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        body_start = pos + 8
        body_end = body_start + length
        if body_end + 4 > total:
            msg = "Truncated PNG chunk"
            raise VisionDecodeError(msg)
        body = data[body_start:body_end]
        if ctype == b"IHDR":
            if length < 13:
                msg = "Short PNG IHDR"
                raise VisionDecodeError(msg)
            width, height = struct.unpack(">II", body[:8])
            bit_depth = body[8]
            color_type = body[9]
            interlace = body[12]
        elif ctype == b"PLTE":
            palette = [tuple(body[i : i + 3]) for i in range(0, len(body) - 2, 3)]
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
        pos = body_end + 4  # skip the CRC

    if width is None or height is None or bit_depth is None or color_type is None:
        msg = "PNG missing IHDR"
        raise VisionDecodeError(msg)
    if interlace != 0:
        msg = "Interlaced PNG not supported"
        raise VisionDecodeError(msg)
    if bit_depth != 8:
        msg = f"Only 8-bit PNG supported, got bit-depth {bit_depth}"
        raise VisionDecodeError(msg)

    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        msg = f"PNG zlib decompression failed: {exc}"
        raise VisionDecodeError(msg) from exc

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        msg = f"Unsupported PNG color type: {color_type}"
        raise VisionDecodeError(msg)

    row_len = width * channels
    stride = row_len + 1
    scanlines: list[bytearray] = []
    prev = bytearray(row_len)
    for y in range(height):
        start = y * stride
        if start + stride > len(raw):
            msg = "Truncated PNG pixel data"
            raise VisionDecodeError(msg)
        filter_type = raw[start]
        line = bytearray(raw[start + 1 : start + stride])
        _unfilter(line, prev, filter_type, channels)
        scanlines.append(line)
        prev = line

    if color_type == 2:
        rows = [[(line[i], line[i + 1], line[i + 2]) for i in range(0, row_len, 3)] for line in scanlines]
    elif color_type == 6:
        rows = [[_blend(line[i], line[i + 1], line[i + 2], line[i + 3]) for i in range(0, row_len, 4)] for line in scanlines]
    elif color_type == 0:
        rows = [[(v, v, v) for v in line] for line in scanlines]
    elif color_type == 4:
        rows = [
            [_blend(v, v, v, line[i + 1]) for i, v in enumerate(line[::2])]
            for line in scanlines
        ]
    else:  # color_type == 3 (palette)
        if not palette:
            msg = "PNG palette image with no PLTE chunk"
            raise VisionDecodeError(msg)
        rows = [[palette[v] if v < len(palette) else (0, 0, 0) for v in line] for line in scanlines]

    return Image(width=width, height=height, pixels=rows)


def _decode_bmp(data: bytes) -> Image:
    """Decode a 24/32-bit, uncompressed BMP (BI_RGB)."""
    if len(data) < 54 or data[:2] != b"BM":
        msg = "Not a BMP image"
        raise VisionDecodeError(msg)
    pixel_offset = struct.unpack("<I", data[10:14])[0]
    width = struct.unpack("<i", data[18:22])[0]
    height_raw = struct.unpack("<i", data[22:26])[0]
    bit_count = struct.unpack("<H", data[28:30])[0]
    compression = struct.unpack("<I", data[30:34])[0]
    if width <= 0:
        msg = "BMP width must be positive"
        raise VisionDecodeError(msg)
    if compression != 0:
        msg = f"Compressed BMP not supported (compression={compression})"
        raise VisionDecodeError(msg)
    if bit_count not in (24, 32):
        msg = f"Only 24/32-bit BMP supported, got {bit_count}"
        raise VisionDecodeError(msg)

    height = abs(height_raw)
    top_down = height_raw < 0
    bytes_per_pixel = bit_count // 8
    row_size = (width * bytes_per_pixel + 3) // 4 * 4
    needed = pixel_offset + height * row_size
    if needed > len(data):
        msg = "Truncated BMP pixel data"
        raise VisionDecodeError(msg)

    rows: list[list[tuple[int, int, int]]] = []
    for y in range(height):
        source_row = y if top_down else height - 1 - y
        base = pixel_offset + source_row * row_size
        row = [
            (data[base + x * bytes_per_pixel + 2], data[base + x * bytes_per_pixel + 1], data[base + x * bytes_per_pixel])
            for x in range(width)
        ]
        rows.append(row)
    return Image(width=width, height=height, pixels=rows)


def _decode_with_pil(data: bytes) -> Image | None:
    """Decode using Pillow if available (JPEG, GIF, WebP, ...)."""
    try:
        from PIL import Image as PILImage  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        from io import BytesIO

        with PILImage.open(BytesIO(data)) as pil_img:
            pil_img = pil_img.convert("RGB")
            width, height = pil_img.size
            pixels = list(pil_img.getdata())
            rows = [pixels[y * width : (y + 1) * width] for y in range(height)]
        return Image(width=width, height=height, pixels=rows)
    except Exception:
        return None


def decode_image(data: bytes) -> Image:
    """Decode image bytes into an `Image` using the fastest available path.

    Tries the pure-stdlib PNG and BMP decoders first, then Pillow as a fallback
    for other formats. Raises `VisionDecodeError` if nothing can decode it.
    """
    if not data:
        msg = "Empty image payload"
        raise VisionDecodeError(msg)
    for decoder in (_decode_png, _decode_bmp):
        try:
            return decoder(data)
        except VisionDecodeError:
            continue
    via_pil = _decode_with_pil(data)
    if via_pil is not None:
        return via_pil
    msg = "Unsupported image format (supported: PNG, BMP; Pillow optional for JPEG/GIF/WebP)"
    raise VisionDecodeError(msg)
