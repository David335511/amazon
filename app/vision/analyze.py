"""Deterministic, provider-independent image analysis.

Every function here operates on the internal `Image` pixel grid using only the
standard library, so the vision subsystem provides real, reproducible features
(embedding, color, shape, size, barcode signature, logo signature) with zero
external dependencies. Enhanced providers (OCR, true barcode decoding, named
logo recognition) plug in through the `VisionProvider` seam.
"""

from __future__ import annotations

import math

from app.vision.models import (
    BarcodeInfo,
    ColorInfo,
    Image,
    LogoSignature,
    PackageInfo,
    ShapeInfo,
    SizeInfo,
)


def downscale(image: Image, target_width: int, target_height: int) -> Image:
    """Nearest-neighbour resize to a target grid (keeps it cheap and bounded)."""
    if target_width <= 0 or target_height <= 0:
        return image
    if image.width <= target_width and image.height <= target_height:
        return image
    rows: list[list[tuple[int, int, int]]] = []
    for ty in range(target_height):
        sy = min(int(ty * image.height / target_height), image.height - 1)
        row = [
            image.pixels[sy][min(int(tx * image.width / target_width), image.width - 1)]
            for tx in range(target_width)
        ]
        rows.append(row)
    return Image(width=target_width, height=target_height, pixels=rows)


def compute_embedding(image: Image, grid: int = 16) -> list[float]:
    """A deterministic visual embedding: a normalized RGB grid.

    Downscales to ``grid x grid`` and flattens RGB (0..1) into a vector of
    length ``grid*grid*3``. Cosine similarity on this vector is a fast, robust
    measure of overall visual similarity.
    """
    small = downscale(image, grid, grid)
    vector: list[float] = []
    for row in small.pixels:
        for r, g, b in row:
            vector.extend((r / 255.0, g / 255.0, b / 255.0))
    return vector


def compute_color_histogram(
    image: Image,
    buckets: int = 4,
    dominant_count: int = 5,
) -> tuple[list[float], list[ColorInfo]]:
    """Quantized RGB color histogram plus dominant colors.

    Returns (normalized histogram vector, top dominant colors). The histogram
    supports color comparison via histogram intersection.
    """
    small = downscale(image, 32, 32)
    n = max(1, buckets)
    hist = [0.0] * (n * n * n)
    for row in small.pixels:
        for r, g, b in row:
            ri = min(n - 1, int(r / 256 * n))
            gi = min(n - 1, int(g / 256 * n))
            bi = min(n - 1, int(b / 256 * n))
            hist[ri * n * n + gi * n + bi] += 1.0
    total = sum(hist)
    if total <= 0:
        return hist, []
    normalized = [h / total for h in hist]

    order = sorted(range(len(hist)), key=lambda i: hist[i], reverse=True)[:dominant_count]
    colors: list[ColorInfo] = []
    for index in order:
        if hist[index] <= 0:
            continue
        ri, gi, bi = index // (n * n), (index // n) % n, index % n
        r = int((ri + 0.5) * 256 / n)
        g = int((gi + 0.5) * 256 / n)
        b = int((bi + 0.5) * 256 / n)
        colors.append(
            ColorInfo(
                hex=f"#{r:02x}{g:02x}{b:02x}",
                r=r,
                g=g,
                b=b,
                fraction=round(hist[index] / total, 4),
            )
        )
    return normalized, colors


def compute_shape(image: Image, grid: int = 8) -> tuple[list[float], ShapeInfo]:
    """Normalized luminance grid (shape signature) plus coarse shape info."""
    small = downscale(image, grid, grid)
    flat: list[float] = []
    for row in small.pixels:
        for r, g, b in row:
            flat.append((0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0)
    norm = math.sqrt(sum(v * v for v in flat))
    signature = [v / norm for v in flat] if norm > 0 else flat

    aspect = image.width / max(1, image.height)
    orientation = "square" if 0.85 <= aspect <= 1.18 else ("landscape" if aspect > 1.18 else "portrait")
    return signature, ShapeInfo(
        aspect_ratio=round(aspect, 3),
        orientation=orientation,
        pixel_area=image.width * image.height,
    )


def compute_size(image: Image) -> SizeInfo:
    """Relative size/proportion information (physical size needs external scale)."""
    aspect = image.width / max(1, image.height)
    return SizeInfo(
        aspect_ratio=round(aspect, 3),
        pixel_area=image.width * image.height,
        width=image.width,
        height=image.height,
    )


def detect_barcode(image: Image, transition_threshold: int = 28) -> list[BarcodeInfo]:
    """Heuristic barcode detection via vertical-edge density.

    A barcode is a periodic high-contrast vertical-line structure. We measure
    luminance transitions across columns on a few rows; if the density is high
    enough, we report a barcode-like region. Value decoding requires a provider
    with a barcode library.
    """
    small = downscale(image, 96, 96)
    if small.height < 3:
        return []
    sample_rows = [0, small.height // 2, small.height - 1]
    transitions = 0.0
    rows_checked = 0
    for ry in sample_rows:
        row = small.pixels[ry]
        luminance = [0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in row]
        count = sum(
            1 for i in range(1, len(luminance)) if abs(luminance[i] - luminance[i - 1]) > 40
        )
        transitions += count
        rows_checked += 1
    if rows_checked == 0 or small.width == 0:
        return []
    per_100 = transitions / rows_checked * 100.0 / max(1, small.width)
    confidence = min(1.0, per_100 / max(1, transition_threshold))
    if confidence >= 0.5:
        return [
            BarcodeInfo(
                detected=True,
                barcode_type="barcode_like",
                confidence=round(confidence, 3),
            )
        ]
    return []


def detect_logo(image: Image) -> list[LogoSignature]:
    """A deterministic signature for a logo-like (most saturated) region.

    Finds the most saturated dominant color region and returns a signature
    (color + spatial fraction) that supports *comparison* between images. Named
    logo recognition requires an enhanced provider.
    """
    small = downscale(image, 32, 32)
    best: tuple[float, int, int, int] | None = None
    for row in small.pixels:
        for r, g, b in row:
            maximum = max(r, g, b)
            minimum = min(r, g, b)
            saturation = 0.0 if maximum == 0 else (maximum - minimum) / maximum
            score = saturation + (maximum / 255.0) * 0.2
            if best is None or score > best[0]:
                best = (score, r, g, b)
    if best is None:
        return []
    _, r, g, b = best
    # Fraction of pixels close to that saturated color.
    near = sum(
        1
        for row in small.pixels
        for pr, pg, pb in row
        if abs(pr - r) <= 40 and abs(pg - g) <= 40 and abs(pb - b) <= 40
    )
    total = max(1, small.width * small.height)
    confidence = min(1.0, best[0])
    if confidence < 0.2:
        return []
    return [
        LogoSignature(
            hex=f"#{r:02x}{g:02x}{b:02x}",
            r=r,
            g=g,
            b=b,
            fraction=round(near / total, 4),
            confidence=round(confidence, 3),
        )
    ]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors (0..1, clamped)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def histogram_intersection(a: list[float], b: list[float]) -> float:
    """Histogram intersection similarity (0..1)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(min(x, y) for x, y in zip(a, b, strict=False))


def build_package(shape: ShapeInfo, colors: list[ColorInfo]) -> PackageInfo:
    """Summarize packaging-level features (shape + dominant colors)."""
    return PackageInfo(
        aspect_ratio=shape.aspect_ratio,
        orientation=shape.orientation,
        dominant_colors=colors,
    )
