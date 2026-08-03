"""Computer-vision subsystem.

Gives the platform provider-independent image understanding: decoding, image
embeddings, color/shape/size/package comparison, model-number scanning, and
heuristic barcode/logo detection — all with zero required third-party
dependencies (pure Python standard library).

Matching fuses these vision features with catalog signals (UPC, title, brand,
attributes) into a single confidence score with a per-feature matched/unmatched
breakdown and a human-readable explanation.

The `VisionProvider` seam keeps real OCR, true barcode decoding, named logo
recognition, and remote embeddings pluggable (Tesseract or any generic HTTP
vision service) without coupling the subsystem to a vendor.

Exposed through `VisionManager` and the `/api/v1/vision` endpoints.
"""

from app.vision.config import VisionConfig
from app.vision.errors import (
    VisionDecodeError,
    VisionError,
    VisionUnsupportedError,
    VisionValidationError,
)
from app.vision.manager import VisionManager
from app.vision.models import (
    BarcodeInfo,
    ColorInfo,
    FeatureMatch,
    FeatureSimilarity,
    Image,
    ImageAnalysis,
    LogoSignature,
    PackageInfo,
    ShapeInfo,
    SimilarityTarget,
    SizeInfo,
    VisionCapabilities,
    VisionCapability,
    VisionComparison,
    VisionMatchResult,
)
from app.vision.providers import (
    HTTPVisionProvider,
    LocalVisionProvider,
    TesseractOCRProvider,
    VisionProvider,
    build_vision_provider,
)

__all__ = [
    "BarcodeInfo",
    "ColorInfo",
    "FeatureMatch",
    "FeatureSimilarity",
    "HTTPVisionProvider",
    "Image",
    "ImageAnalysis",
    "LocalVisionProvider",
    "LogoSignature",
    "PackageInfo",
    "ShapeInfo",
    "SimilarityTarget",
    "SizeInfo",
    "TesseractOCRProvider",
    "VisionCapabilities",
    "VisionCapability",
    "VisionComparison",
    "VisionConfig",
    "VisionDecodeError",
    "VisionError",
    "VisionManager",
    "VisionMatchResult",
    "VisionProvider",
    "VisionUnsupportedError",
    "VisionValidationError",
    "build_vision_provider",
]
