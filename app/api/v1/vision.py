"""Computer-vision API.

The router talks ONLY to `VisionManager` (via DI); it contains no vision-domain
logic itself. Endpoints accept image uploads (multipart) plus optional catalog
signals and return analysis / comparison / match results.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.dependencies import get_vision_manager
from app.vision import (
    ImageAnalysis,
    SimilarityTarget,
    VisionCapabilities,
    VisionComparison,
    VisionManager,
    VisionMatchResult,
)
from app.vision.errors import VisionDecodeError, VisionValidationError

router = APIRouter(prefix="/vision", tags=["vision"])

ManagerDep = Annotated[VisionManager, Depends(get_vision_manager)]


def _read_file(file: UploadFile | None, field: str) -> bytes:
    if file is None:
        msg = f"'{field}' file is required"
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=msg)
    data = file.file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"'{field}' file is empty",
        )
    return data


def _parse_attributes(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"attributes must be a JSON object: {exc}",
        ) from exc
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="attributes must be a JSON object",
        )
    return value


def _handle_vision_error(exc: Exception) -> None:
    if isinstance(exc, (VisionDecodeError, VisionValidationError)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.post("/analyze", response_model=ImageAnalysis)
async def analyze(
    manager: ManagerDep,
    file: Annotated[UploadFile, File()],
) -> ImageAnalysis:
    """Analyze an uploaded image and extract all vision features."""
    data = _read_file(file, "file")
    try:
        return await manager.analyze(data)
    except Exception as exc:
        _handle_vision_error(exc)
        raise


@router.post("/compare", response_model=VisionComparison)
async def compare(
    manager: ManagerDep,
    observed: Annotated[UploadFile, File(description="Image of the observed product")],
    reference: Annotated[UploadFile, File(description="Image of the reference product")],
) -> VisionComparison:
    """Compare two images feature by feature (embedding/color/shape/size/...)."""
    obs_data = _read_file(observed, "observed")
    ref_data = _read_file(reference, "reference")
    try:
        return await manager.compare(obs_data, ref_data)
    except Exception as exc:
        _handle_vision_error(exc)
        raise


@router.post("/match", response_model=VisionMatchResult)
async def match(
    manager: ManagerDep,
    file: Annotated[UploadFile, File(description="Image of the observed product")],
    reference_title: Annotated[str, Form()] = "",
    reference_upc: Annotated[str, Form()] = "",
    reference_brand: Annotated[str, Form()] = "",
    reference_attributes: Annotated[str, Form(description="JSON object")] = "",
    observed_upc: Annotated[str, Form()] = "",
    observed_brand: Annotated[str, Form()] = "",
    observed_attributes: Annotated[str, Form(description="JSON object")] = "",
) -> VisionMatchResult:
    """Match an uploaded image against a reference product.

    Fuses vision similarity with the reference's UPC/title/brand/attributes
    (and any observed catalog signals) into a confidence score with a matched /
    unmatched feature breakdown and an explanation.
    """
    data = _read_file(file, "file")
    try:
        analysis = await manager.analyze(data)
        observed = SimilarityTarget(
            analysis=analysis,
            upc=observed_upc or None,
            brand=observed_brand or None,
            attributes=_parse_attributes(observed_attributes),
        )
        reference = SimilarityTarget(
            title=reference_title or None,
            upc=reference_upc or None,
            brand=reference_brand or None,
            attributes=_parse_attributes(reference_attributes),
        )
        return await manager.match(observed, reference)
    except Exception as exc:
        _handle_vision_error(exc)
        raise


@router.get("/capabilities", response_model=VisionCapabilities)
async def capabilities(manager: ManagerDep) -> VisionCapabilities:
    """Report the capabilities the configured provider genuinely supports."""
    return manager.capabilities()
