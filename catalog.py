"""
catalog.py — Florida Man Drops Automation Factory
===================================================
Phase 2: Metadata Validation, Quality Control & Local Catalog Management

Responsibilities:
  1. Load generated concepts from generated_concepts.json
  2. Run Pillow-based print-ready validation on each image file
  3. Apply pre-flight quality checks (DPI, format, transparency, dimensions)
  4. Score and filter concepts by confidence threshold
  5. Upscale images that pass concept checks but fail DPI requirements
  6. Save approved concepts to approved_catalog.json for upload phase
  7. Log all rejections with reasons for audit trail

Uses tenacity for retry on file I/O and image processing operations.
"""

import os
import json
import logging
import shutil
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

from PIL import Image, ImageFilter
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    RetryError,
)

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("catalog")

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
CONCEPTS_FILE       = Path(os.getenv("CONCEPTS_FILE", "output/generated_concepts.json"))
APPROVED_FILE       = Path(os.getenv("APPROVED_FILE", "output/approved_catalog.json"))
REJECTED_FILE       = Path(os.getenv("REJECTED_FILE", "output/rejected_catalog.json"))
UPSCALED_DIR        = Path(os.getenv("UPSCALED_DIR", "output/upscaled"))
MIN_DPI             = int(os.getenv("MIN_DPI", "300"))
MIN_CONFIDENCE      = int(os.getenv("MIN_CONFIDENCE", "75"))
PRINT_WIDTH_INCHES  = float(os.getenv("PRINT_WIDTH_INCHES", "12"))
PRINT_HEIGHT_INCHES = float(os.getenv("PRINT_HEIGHT_INCHES", "16"))
TARGET_WIDTH_PX     = int(PRINT_WIDTH_INCHES * MIN_DPI)   # 3600
TARGET_HEIGHT_PX    = int(PRINT_HEIGHT_INCHES * MIN_DPI)  # 4800

UPSCALED_DIR.mkdir(parents=True, exist_ok=True)
APPROVED_FILE.parent.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────
@dataclass
class CatalogEntry:
    id: str
    title: str
    headline: str
    description: str
    trend_category: str
    confidence_score: int
    is_limited_drop: bool
    dalle_image_prompt: str
    local_image_path: str
    print_ready_path: str          # Path to the upscaled/validated image
    image_width: int
    image_height: int
    image_dpi: int
    image_format: str
    has_transparency: bool
    generated_at: str
    approved_at: str
    validation_notes: str


@dataclass
class RejectedEntry:
    id: str
    title: str
    rejection_reason: str
    rejected_at: str


# ─────────────────────────────────────────────
# Pillow: Print-Ready Validation
# ─────────────────────────────────────────────
def validate_print_specs(path: Path, concept_id: str) -> dict:
    """
    Validate an image file against print-ready requirements.
    Returns a dict with:
      - passes: bool
      - needs_upscale: bool
      - reason: str (if fails)
      - metadata: dict
    """
    if not path.exists():
        return {
            "passes": False,
            "needs_upscale": False,
            "reason": f"Image file not found: {path}",
            "metadata": {},
        }

    img = Image.open(path)
    width, height = img.size
    mode = img.mode
    fmt = img.format or "PNG"
    has_transparency = mode in ("RGBA", "LA") or (
        mode == "P" and "transparency" in img.info
    )
    dpi_info = img.info.get("dpi", (72, 72))
    dpi = int(min(dpi_info)) if isinstance(dpi_info, (tuple, list)) else int(dpi_info)

    notes = []
    passes = True
    needs_upscale = False

    # Check 1: Minimum pixel dimensions
    if width < 512 or height < 512:
        return {
            "passes": False,
            "needs_upscale": False,
            "reason": f"Image too small: {width}x{height}px (minimum 512x512)",
            "metadata": {"width": width, "height": height, "dpi": dpi, "format": fmt},
        }

    # Check 2: DPI / resolution for print
    if width < TARGET_WIDTH_PX or height < TARGET_HEIGHT_PX:
        needs_upscale = True
        notes.append(
            f"Image {width}x{height} below target {TARGET_WIDTH_PX}x{TARGET_HEIGHT_PX} — upscale required"
        )
        log.warning(f"[{concept_id}] {notes[-1]}")
    else:
        notes.append(f"Resolution OK: {width}x{height}px")

    # Check 3: Format should be PNG for transparency support
    if fmt not in ("PNG", "WEBP"):
        notes.append(f"Format {fmt} — will convert to PNG")
        log.info(f"[{concept_id}] Format conversion needed: {fmt} → PNG")

    # Check 4: Transparency (preferred but not blocking)
    if not has_transparency:
        notes.append("No transparency channel — background removal may be needed")
        log.info(f"[{concept_id}] No alpha channel detected (mode={mode})")

    log.info(
        f"[{concept_id}] Validation — {width}x{height}px, DPI={dpi}, "
        f"mode={mode}, transparency={has_transparency}, upscale_needed={needs_upscale}"
    )

    return {
        "passes": passes,
        "needs_upscale": needs_upscale,
        "reason": None,
        "metadata": {
            "width": width,
            "height": height,
            "dpi": dpi,
            "format": fmt,
            "has_transparency": has_transparency,
            "mode": mode,
        },
        "notes": "; ".join(notes),
    }


# ─────────────────────────────────────────────
# Pillow: Upscale to Print Resolution
# ─────────────────────────────────────────────
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(log, logging.WARNING),
)
def upscale_to_print_resolution(
    src_path: Path, concept_id: str
) -> Path:
    """
    Upscale the image to TARGET_WIDTH_PX x TARGET_HEIGHT_PX using Lanczos resampling.
    Saves to UPSCALED_DIR and returns the new path.
    Retries up to 3 times on I/O or processing errors.
    """
    log.info(
        f"[{concept_id}] Upscaling to {TARGET_WIDTH_PX}x{TARGET_HEIGHT_PX}px..."
    )
    img = Image.open(src_path)

    # Convert to RGBA to preserve/add transparency
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    # Upscale with Lanczos (best quality for enlargement)
    upscaled = img.resize((TARGET_WIDTH_PX, TARGET_HEIGHT_PX), Image.LANCZOS)

    # Apply light sharpening after upscale
    upscaled = upscaled.filter(ImageFilter.SHARPEN)

    # Save with DPI metadata
    dest_path = UPSCALED_DIR / f"{concept_id}_print_ready.png"
    upscaled.save(dest_path, format="PNG", dpi=(MIN_DPI, MIN_DPI))
    log.info(f"[{concept_id}] Upscaled image saved → {dest_path}")
    return dest_path


# ─────────────────────────────────────────────
# Pillow: Composite FMA Badge onto Tee Image
# ─────────────────────────────────────────────
BADGE_PATH = Path(os.getenv("FMA_BADGE_PATH", "assets/fma_retro_badge_logo.png"))
BADGE_SIZE_PX = int(os.getenv("FMA_BADGE_SIZE_PX", "320"))  # badge diameter in pixels
# Placement: bottom-right of the print area (sleeve-adjacent / tag area)
# At 3600×4800 a 320px badge sits ~200px from right and ~200px from bottom
BADGE_MARGIN_RIGHT  = int(os.getenv("FMA_BADGE_MARGIN_RIGHT", "200"))
BADGE_MARGIN_BOTTOM = int(os.getenv("FMA_BADGE_MARGIN_BOTTOM", "200"))


def composite_fma_badge(tee_path: Path, concept_id: str) -> Path:
    """
    Composite the FMA retro badge logo onto the tee design image.
    The badge is placed at the bottom-right corner (tag / sleeve area).
    Returns the path to the composited image (overwrites tee_path in-place).
    If the badge asset is missing the function is a no-op and returns tee_path.
    """
    if not BADGE_PATH.exists():
        log.warning(
            f"[{concept_id}] FMA badge not found at {BADGE_PATH} — skipping badge injection"
        )
        return tee_path

    log.info(f"[{concept_id}] Compositing FMA badge ({BADGE_SIZE_PX}px) onto {tee_path.name}")

    tee = Image.open(tee_path).convert("RGBA")
    badge_raw = Image.open(BADGE_PATH).convert("RGBA")

    # Resize badge to target diameter (square)
    badge = badge_raw.resize((BADGE_SIZE_PX, BADGE_SIZE_PX), Image.LANCZOS)

    # Calculate paste position: bottom-right with margin
    tee_w, tee_h = tee.size
    paste_x = tee_w - BADGE_SIZE_PX - BADGE_MARGIN_RIGHT
    paste_y = tee_h - BADGE_SIZE_PX - BADGE_MARGIN_BOTTOM

    # Paste using badge's own alpha as mask
    tee.paste(badge, (paste_x, paste_y), badge)

    # Save back to same path (PNG to preserve alpha)
    tee.save(tee_path, format="PNG", dpi=(MIN_DPI, MIN_DPI))
    log.info(f"[{concept_id}] Badge composited at ({paste_x}, {paste_y}) → {tee_path}")
    return tee_path


# ─────────────────────────────────────────────
# Pre-flight: Process One Concept
# ─────────────────────────────────────────────
def process_concept(raw: dict) -> tuple[Optional[CatalogEntry], Optional[RejectedEntry]]:
    """
    Run the full pre-flight check on a single concept.
    Returns (CatalogEntry, None) on success or (None, RejectedEntry) on failure.
    """
    concept_id = raw.get("id", "unknown")
    title = raw.get("title", "UNTITLED")
    image_path = Path(raw.get("local_image_path", ""))

    log.info(f"[{concept_id}] Pre-flight check: {title}")

    # Check 1: Confidence score threshold
    confidence = int(raw.get("confidence_score", 0))
    if confidence < MIN_CONFIDENCE:
        reason = f"Confidence score {confidence} below threshold {MIN_CONFIDENCE}"
        log.warning(f"[{concept_id}] REJECTED — {reason}")
        return None, RejectedEntry(
            id=concept_id,
            title=title,
            rejection_reason=reason,
            rejected_at=datetime.utcnow().isoformat(),
        )

    # Check 2: Image file validation
    validation = validate_print_specs(image_path, concept_id)
    if not validation["passes"]:
        reason = validation["reason"]
        log.warning(f"[{concept_id}] REJECTED — {reason}")
        return None, RejectedEntry(
            id=concept_id,
            title=title,
            rejection_reason=reason,
            rejected_at=datetime.utcnow().isoformat(),
        )

    # Check 3: Upscale if needed
    print_ready_path = image_path
    meta = validation["metadata"]

    if validation["needs_upscale"]:
        try:
            print_ready_path = upscale_to_print_resolution(image_path, concept_id)
            # Re-validate after upscale
            post_validation = validate_print_specs(print_ready_path, concept_id)
            meta = post_validation["metadata"]
        except RetryError as e:
            reason = f"Upscale failed after all retries: {e}"
            log.error(f"[{concept_id}] REJECTED — {reason}")
            return None, RejectedEntry(
                id=concept_id,
                title=title,
                rejection_reason=reason,
                rejected_at=datetime.utcnow().isoformat(),
            )

    # Step 4: Composite FMA badge onto the print-ready image
    print_ready_path = composite_fma_badge(print_ready_path, concept_id)

    # All checks passed — build catalog entry
    entry = CatalogEntry(
        id=concept_id,
        title=title,
        headline=raw.get("headline", title),
        description=raw.get("description", ""),
        trend_category=raw.get("trend_category", "florida_lifestyle"),
        confidence_score=confidence,
        is_limited_drop=bool(raw.get("is_limited_drop", False)),
        dalle_image_prompt=raw.get("dalle_image_prompt", ""),
        local_image_path=str(image_path),
        print_ready_path=str(print_ready_path),
        image_width=meta.get("width", 0),
        image_height=meta.get("height", 0),
        image_dpi=meta.get("dpi", MIN_DPI),
        image_format=meta.get("format", "PNG"),
        has_transparency=meta.get("has_transparency", False),
        generated_at=raw.get("generated_at", datetime.utcnow().isoformat()),
        approved_at=datetime.utcnow().isoformat(),
        validation_notes=validation.get("notes", ""),
    )

    log.info(f"[{concept_id}] ✓ APPROVED: {title}")
    return entry, None


# ─────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────
def run() -> list[CatalogEntry]:
    """
    Full catalog phase:
    1. Load generated_concepts.json
    2. Run pre-flight checks on each concept
    3. Save approved/rejected to separate JSON files
    Returns list of approved CatalogEntry objects.
    """
    log.info("=" * 60)
    log.info("FLORIDA MAN DROPS — CATALOG PHASE STARTED")
    log.info("=" * 60)

    if not CONCEPTS_FILE.exists():
        log.error(f"Concepts file not found: {CONCEPTS_FILE}")
        log.error("Run generate.py first to create concepts.")
        return []

    raw_concepts = json.loads(CONCEPTS_FILE.read_text())
    log.info(f"Loaded {len(raw_concepts)} concepts from {CONCEPTS_FILE}")

    approved: list[CatalogEntry] = []
    rejected: list[RejectedEntry] = []

    for i, raw in enumerate(raw_concepts):
        log.info(f"--- Processing {i+1}/{len(raw_concepts)}: {raw.get('title', '?')} ---")
        entry, rejection = process_concept(raw)
        if entry:
            approved.append(entry)
        elif rejection:
            rejected.append(rejection)

    # Save results
    APPROVED_FILE.write_text(json.dumps([asdict(e) for e in approved], indent=2))
    REJECTED_FILE.write_text(json.dumps([asdict(r) for r in rejected], indent=2))

    log.info(f"Approved: {len(approved)} | Rejected: {len(rejected)}")
    log.info(f"Approved catalog → {APPROVED_FILE}")
    log.info(f"Rejected log → {REJECTED_FILE}")

    log.info("=" * 60)
    log.info(f"CATALOG PHASE COMPLETE — {len(approved)} concepts approved")
    log.info("=" * 60)
    return approved


if __name__ == "__main__":
    entries = run()
    print(f"\nApproved {len(entries)} concepts for upload:")
    for e in entries:
        print(f"  [{e.confidence_score}%] {e.title} → {e.print_ready_path}")
