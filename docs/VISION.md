# Computer-Vision Module

Provider-independent image understanding for the Amazon AI Commerce Platform.
Decodes images, extracts vision features, and fuses them with catalog signals
(UPC, title, brand, attributes) into a single confidence score with a matched /
unmatched feature breakdown and a human-readable explanation.

**Everything runs on the Python standard library** — no required third-party
image or vision dependency. Real OCR, true barcode decoding, and named logo
recognition plug in through a `VisionProvider` seam.

---

## Capabilities

| Capability | Description | Local (default) | Provider seam |
|---|---|---|---|
| **Image embeddings** | A deterministic visual embedding (normalized RGB grid) for overall similarity | ✅ | ✅ remote vector |
| **OCR** | Text extraction from pixels | ❌ (none) | ✅ Tesseract / HTTP |
| **Logo detection** | Saturated-region signature; comparison between images | ✅ heuristic | ✅ named recognition |
| **Package comparison** | Shape + dominant-color packaging summary | ✅ | ✅ |
| **Color comparison** | Quantized RGB histogram intersection + dominant colors | ✅ | ✅ |
| **Shape comparison** | Normalized luminance grid + aspect ratio | ✅ | ✅ |
| **Size comparison** | Relative proportions (aspect ratio + pixel area) | ✅ | ✅ |
| **Model-number detection** | Regex scan of OCR/title/attributes for model codes | ✅ | — |
| **Barcode detection** | Presence & style via vertical-edge density | ✅ heuristic | ✅ decode (zbar/OpenCV) |

> **Physical size** cannot be inferred from pixels alone. Size is expressed as
> *proportions* (aspect ratio + relative area); supply real-world scale in an
> attribute to derive physical dimensions.

---

## Architecture

```
app/vision/
  models.py     Image (internal pixel grid) + Pydantic result types
  decode.py     Pure-stdlib PNG (8-bit, types 0/2/3/4/6) + BMP decoders; optional PIL
  analyze.py    Deterministic analyzers: embedding, color, shape, size, barcode, logo
  text.py       Model-number extraction, brand/title similarity, attribute overlap
  providers.py  VisionProvider ABC + Local + Tesseract + HTTP + build_vision_provider()
  matcher.py    Fuses vision + catalog signals -> VisionMatchResult
  manager.py    VisionManager facade (the only entry point)
  config.py     VisionConfig (weights, thresholds, provider)
```

### Provider independence

`VisionProvider` is the **only** contract for enhanced capabilities:

| Method | Local returns | Meaning |
|---|---|---|
| `decode(bytes)` | `None` | use the stdlib PNG/BMP decoder |
| `ocr(image)` | `""` | no real OCR without an enhanced provider |
| `embed(image)` | `None` | use the local deterministic embedder |
| `detect_logos` / `detect_barcodes` | `[]` | fall back to local heuristics |

Select via config `provider: local` (default, always available), `tesseract`
(real OCR when `pytesseract` is installed), or `http` (any generic remote vision
service configured by `base_url` / `api_key`). The subsystem never depends on a
specific vendor.

### Matching (the core)

`VisionManager.match(observed, reference)` fuses signals:

- **Catalog**: UPC, brand, title, attributes.
- **Vision**: embedding, color, shape, size, package, barcode, logo, model number.

Each available signal contributes its `score × weight`; the result is normalized
over the weights of *available* signals. A **definitive contradiction** (both
UPCs present but different, or both brands present but different) multiplies
confidence down by `hard_mismatch_penalty` per contradiction. Features scoring
`>= match_threshold` land in `matched_features`; the rest in `unmatched_features`.

```text
Confidence 0.84; visual similarity 0.91; matched: upc (1.00), brand (1.00),
embedding (0.99), color (0.95); unmatched: title (0.12)
```

---

## API

All routes are under `/api/v1/vision` and require API-key auth when Phase 0
security is enabled.

| Endpoint | Method | Purpose |
|---|---|---|
| `/analyze` | POST | Upload an image → full `ImageAnalysis` |
| `/compare` | POST | Two images → `VisionComparison` (embedding/color/shape/size/...) |
| `/match` | POST | Image + reference UPC/title/brand/attributes → `VisionMatchResult` |
| `/capabilities` | GET | Which capabilities the configured provider supports |

### Example: match

```
POST /api/v1/vision/match
Content-Type: multipart/form-data
  file                (image of the observed product)
  reference_upc       012345678905
  reference_brand     Acme
  reference_title     Acme Widget
  reference_attributes  {"color":"black"}
  observed_upc        012345678905
```

Response:

```json
{
  "confidence": 0.84,
  "overall_similarity": 0.91,
  "matched_features": [
    {"feature":"upc","kind":"catalog","matched":true,"score":1.0,"detail":"UPC matches (012345678905)","weight":0.3}
  ],
  "unmatched_features": [
    {"feature":"title","kind":"catalog","matched":false,"score":0.12,"detail":"title text similarity 0.12","weight":0.15}
  ],
  "explanation": "Confidence 0.84; visual similarity 0.91; matched: upc (1.00); unmatched: title (0.12)",
  "provider_used": "local"
}
```

---

## Wiring

- **DI**: `get_vision_manager()` in `app/core/dependencies.py` (shared, stateless
  manager + provider built from `settings.vision`).
- **Config**: `config/development.yaml` → `vision:` block, validated into
  `VisionConfig`. Signal weights and thresholds are tunable there.
- **API**: `app/api/v1/vision.py`, registered in `app/api/v1/__init__.py`.

### Configuration (`vision:` block)

```yaml
vision:
  enabled: true
  provider: local          # local | tesseract | http
  embed_grid: 16           # NxN visual embedding
  color_buckets: 4         # per-channel histogram buckets
  match_threshold: 0.55    # score >= this => "matched"
  weight_upc: 0.30         # fusion weights (relative)
  weight_brand: 0.15
  weight_title: 0.15
  weight_attributes: 0.10
  weight_embedding: 0.10
  hard_mismatch_penalty: 0.35   # per definitive contradiction
```

---

## Future / Production notes

- **Real OCR / barcode / logo**: `pip install '.[vision]'` (Pillow + pytesseract)
  enables broader decode formats and OCR; a barcode library (zbar/OpenCV) can be
  wired into an enhanced provider for true decode.
- **Persist embeddings**: `ImageAnalysis.embedding` can be stored (like memory
  embeddings) for a product-image gallery and similarity search.
- **Caching**: analysis is deterministic; cache by content-hash for repeated
  images.
- **Bounded compute**: every analyzer downscales to a small grid first, so cost
  is constant regardless of source resolution.
