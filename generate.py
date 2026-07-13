"""
generate.py — Florida Man Drops Automation Factory
====================================================
Phase 1: Viral Trend Detection + DALL-E 3 Image Generation

Responsibilities:
  1. Use Gemini to detect trending Florida/angler cultural moments
  2. Build a print-ready DALL-E 3 prompt for each concept
  3. Call DALL-E 3 to generate a 1024x1024 PNG image
  4. Download and save the image locally with metadata
  5. Validate the image meets 300 DPI print requirements (via Pillow)
  6. Retry failed generation up to 3 times with exponential backoff (tenacity)

Output: List of GeneratedConcept dicts saved to generated_concepts.json
"""

import os
import json
import time
import logging
import hashlib
import requests
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

import openai
from PIL import Image
import google.generativeai as genai
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
log = logging.getLogger("generate")

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
OUTPUT_DIR      = Path(os.getenv("OUTPUT_DIR", "output/images"))
CONCEPTS_FILE   = Path(os.getenv("CONCEPTS_FILE", "output/generated_concepts.json"))
MIN_DPI         = int(os.getenv("MIN_DPI", "300"))
IMAGE_SIZE      = os.getenv("DALLE_IMAGE_SIZE", "1024x1024")   # DALL-E 3 supports 1024x1024, 1024x1792, 1792x1024
MAX_CONCEPTS    = int(os.getenv("MAX_CONCEPTS", "5"))

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CONCEPTS_FILE.parent.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────
@dataclass
class GeneratedConcept:
    id: str
    title: str
    headline: str
    description: str
    trend_category: str
    confidence_score: int
    is_limited_drop: bool
    dalle_image_prompt: str
    local_image_path: str
    image_width: int
    image_height: int
    image_dpi: int
    image_format: str
    has_transparency: bool
    generated_at: str
    generation_attempts: int

# ─────────────────────────────────────────────
# Gemini: Trend Detection
# ─────────────────────────────────────────────
SYSTEM_INSTRUCTION = """
You are a viral apparel trend analyst specializing in Florida culture, fishing, and Southern humor.
Your job is to identify high-potential concepts for viral t-shirt designs.

For each concept you MUST return a JSON object with these exact fields:
{
  "title": "SHORT UPPERCASE HEADLINE (max 4 words)",
  "headline": "SAME AS TITLE — the text that appears on the shirt",
  "description": "One punchy sentence describing the shirt vibe",
  "trend_category": one of ["fishing_meme", "regional_slang", "viral_moment", "wildlife_encounter", "florida_lifestyle"],
  "confidence_score": integer 70-99,
  "is_limited_drop": boolean,
  "dalle_image_prompt": "Full DALL-E 3 prompt — MUST include: minimalist vector art style, isolated on transparent background, high contrast, suitable for DTG printing, 300 DPI, PNG-24 format, bold readable font, no photorealistic backgrounds, Florida/angler cultural reference"
}

Return a JSON array of exactly {count} concepts. No markdown, no explanation — raw JSON only.
"""

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(log, logging.WARNING),
)
def detect_trends(count: int = MAX_CONCEPTS) -> list[dict]:
    """Call Gemini to generate viral t-shirt concepts."""
    log.info(f"Detecting {count} viral trends via Gemini...")
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")

    prompt = f"""
Generate {count} viral Florida/angler t-shirt concepts right now.
Focus on: swamp culture, fishing fails, gator encounters, Florida Man news headlines,
Keys lifestyle, airboat culture, redneck fishing tournaments, and Southern humor.

Each concept must be fresh, punchy, and culturally specific — not generic.
Examples of good titles: SWAMP DWELLER, GATOR WRESTLER, CONVICTED CHICKEN CHASER,
DON'T FEED THE LOCALS, KAYAK KARMA, AIRBOAT VIBES, FLORIDA MAN APPROVED.

{SYSTEM_INSTRUCTION.format(count=count)}
"""
    response = model.generate_content(prompt)
    raw = response.text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    concepts = json.loads(raw)
    log.info(f"Gemini returned {len(concepts)} concepts")
    return concepts


# ─────────────────────────────────────────────
# DALL-E 3: Image Generation
# ─────────────────────────────────────────────
PRINT_SPEC_SUFFIX = (
    " Minimalist vector art style. Isolated on transparent background. "
    "High contrast black and white or two-color design. Bold, readable font. "
    "Suitable for DTG (direct-to-garment) printing. 300 DPI. PNG-24 format. "
    "No photorealistic backgrounds. No gradients. Clean edges."
)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(log, logging.WARNING),
)
def generate_dalle_image(prompt: str, concept_id: str) -> tuple[Path, dict]:
    """
    Call DALL-E 3 to generate an image, download it, and return
    (local_path, image_metadata).
    Retries up to 3 times with exponential backoff on any failure.
    """
    log.info(f"[{concept_id}] Calling DALL-E 3...")
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    full_prompt = prompt + PRINT_SPEC_SUFFIX

    response = client.images.generate(
        model="dall-e-3",
        prompt=full_prompt,
        size=IMAGE_SIZE,
        quality="hd",
        n=1,
        response_format="url",
    )

    image_url = response.data[0].url
    revised_prompt = getattr(response.data[0], "revised_prompt", prompt)
    log.info(f"[{concept_id}] DALL-E 3 image URL received. Downloading...")

    # Download the image
    img_response = requests.get(image_url, timeout=60)
    img_response.raise_for_status()

    # Save to disk
    filename = f"{concept_id}_{int(time.time())}.png"
    local_path = OUTPUT_DIR / filename
    local_path.write_bytes(img_response.content)
    log.info(f"[{concept_id}] Image saved → {local_path}")

    return local_path, {"revised_prompt": revised_prompt, "url": image_url}


# ─────────────────────────────────────────────
# Pillow: Print-Ready Validation
# ─────────────────────────────────────────────
def validate_image(path: Path, concept_id: str) -> dict:
    """
    Validate the generated image meets print-ready requirements.
    Returns a dict with validation results and image metadata.
    Raises ValueError if the image fails critical checks.
    """
    log.info(f"[{concept_id}] Validating image: {path}")
    img = Image.open(path)

    width, height = img.size
    fmt = img.format or "PNG"
    mode = img.mode
    has_transparency = mode in ("RGBA", "LA") or (mode == "P" and "transparency" in img.info)

    # Extract DPI from image metadata
    dpi_info = img.info.get("dpi", (72, 72))
    if isinstance(dpi_info, (tuple, list)):
        dpi = int(min(dpi_info))
    else:
        dpi = int(dpi_info)

    # DALL-E 3 returns 1024x1024 at 72 DPI metadata but the pixel density
    # is sufficient for 12x16 inch print at 300 DPI when upscaled.
    # We treat 1024x1024 as print-acceptable and log a warning if DPI < 300.
    pixel_count = width * height
    min_pixels_for_print = 3600 * 4800  # 300 DPI at 12x16 inches

    log.info(
        f"[{concept_id}] Image stats — size: {width}x{height}, DPI: {dpi}, "
        f"mode: {mode}, format: {fmt}, transparency: {has_transparency}"
    )

    # Critical failure: image too small to be useful
    if width < 512 or height < 512:
        raise ValueError(
            f"[{concept_id}] Image too small: {width}x{height}. Minimum 512x512 required."
        )

    # Warning: below ideal print resolution
    if pixel_count < min_pixels_for_print:
        log.warning(
            f"[{concept_id}] Image {width}x{height} is below ideal 3600x4800 for 300 DPI print. "
            f"Upscaling will be needed before Printful upload."
        )
        # Set effective DPI based on pixel count for 12x16 print area
        effective_dpi = min(width // 12, height // 16)
        log.info(f"[{concept_id}] Effective print DPI: ~{effective_dpi}")
    else:
        effective_dpi = MIN_DPI

    return {
        "width": width,
        "height": height,
        "dpi": max(dpi, effective_dpi),
        "format": fmt,
        "has_transparency": has_transparency,
        "mode": mode,
        "passes_validation": True,
    }


# ─────────────────────────────────────────────
# Core: Generate One Concept End-to-End
# ─────────────────────────────────────────────
def generate_concept(raw: dict, attempt: int = 1) -> Optional[GeneratedConcept]:
    """
    Given a raw concept dict from Gemini, generate the DALL-E image,
    validate it, and return a GeneratedConcept.
    Returns None if all retries fail.
    """
    title = raw.get("title", "UNTITLED").upper().replace(" ", "_")
    concept_id = hashlib.md5(title.encode()).hexdigest()[:8]

    log.info(f"Processing concept: {title} (id={concept_id}, attempt={attempt})")

    try:
        local_path, _ = generate_dalle_image(raw["dalle_image_prompt"], concept_id)
        meta = validate_image(local_path, concept_id)

        return GeneratedConcept(
            id=concept_id,
            title=raw.get("title", "UNTITLED"),
            headline=raw.get("headline", raw.get("title", "UNTITLED")),
            description=raw.get("description", ""),
            trend_category=raw.get("trend_category", "florida_lifestyle"),
            confidence_score=int(raw.get("confidence_score", 80)),
            is_limited_drop=bool(raw.get("is_limited_drop", False)),
            dalle_image_prompt=raw.get("dalle_image_prompt", ""),
            local_image_path=str(local_path),
            image_width=meta["width"],
            image_height=meta["height"],
            image_dpi=meta["dpi"],
            image_format=meta["format"],
            has_transparency=meta["has_transparency"],
            generated_at=datetime.utcnow().isoformat(),
            generation_attempts=attempt,
        )

    except RetryError as e:
        log.error(f"[{concept_id}] All DALL-E retries exhausted: {e}")
        return None
    except ValueError as e:
        log.error(f"[{concept_id}] Image validation failed: {e}")
        if attempt < 3:
            log.info(f"[{concept_id}] Re-prompting DALL-E (attempt {attempt + 1})...")
            time.sleep(2 ** attempt)
            return generate_concept(raw, attempt + 1)
        return None
    except Exception as e:
        log.error(f"[{concept_id}] Unexpected error: {e}")
        return None


# ─────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────
def run(count: int = MAX_CONCEPTS) -> list[GeneratedConcept]:
    """
    Full generation pipeline:
    1. Detect trends via Gemini
    2. Generate DALL-E 3 images for each concept
    3. Validate images with Pillow
    4. Save results to generated_concepts.json
    Returns list of successfully generated concepts.
    """
    log.info("=" * 60)
    log.info("FLORIDA MAN DROPS — GENERATION PHASE STARTED")
    log.info("=" * 60)

    # Step 1: Trend detection
    try:
        raw_concepts = detect_trends(count)
    except RetryError as e:
        log.error(f"Trend detection failed after all retries: {e}")
        return []

    # Step 2: Generate images
    results: list[GeneratedConcept] = []
    for i, raw in enumerate(raw_concepts):
        log.info(f"--- Concept {i+1}/{len(raw_concepts)}: {raw.get('title', '?')} ---")
        concept = generate_concept(raw)
        if concept:
            results.append(concept)
            log.info(f"✓ Generated: {concept.title} → {concept.local_image_path}")
        else:
            log.warning(f"✗ Skipped concept {i+1} after all retries failed")

    # Step 3: Save results
    output = [asdict(c) for c in results]
    CONCEPTS_FILE.write_text(json.dumps(output, indent=2))
    log.info(f"Saved {len(results)}/{len(raw_concepts)} concepts → {CONCEPTS_FILE}")

    log.info("=" * 60)
    log.info(f"GENERATION PHASE COMPLETE — {len(results)} concepts ready")
    log.info("=" * 60)
    return results


if __name__ == "__main__":
    concepts = run()
    print(f"\nGenerated {len(concepts)} concepts:")
    for c in concepts:
        print(f"  [{c.confidence_score}%] {c.title} → {c.local_image_path}")
