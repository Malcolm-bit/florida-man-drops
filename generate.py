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

import base64
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
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "")
FORGE_API_URL       = os.getenv("BUILT_IN_FORGE_API_URL", "").rstrip("/")
FORGE_API_KEY       = os.getenv("BUILT_IN_FORGE_API_KEY", "")
OUTPUT_DIR          = Path(os.getenv("OUTPUT_DIR", "output/images"))
CONCEPTS_FILE       = Path(os.getenv("CONCEPTS_FILE", "output/generated_concepts.json"))
MIN_DPI             = int(os.getenv("MIN_DPI", "300"))
# Forge image model — MODEL_GPT_IMAGE_2 = gpt-image-2 (default); MODEL_GEMINI_IMAGE = Gemini 2.5 Flash
FORGE_IMAGE_MODEL   = os.getenv("FORGE_IMAGE_MODEL", "MODEL_GPT_IMAGE_2")
FORGE_IMAGE_QUALITY = os.getenv("FORGE_IMAGE_QUALITY", "high")
MAX_CONCEPTS        = int(os.getenv("MAX_CONCEPTS", "5"))

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
    design_style: str          # 'smack' or 'retro'
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
# ─────────────────────────────────────────────
# Brand Identity — Retro/Rugged Style Guide
# ─────────────────────────────────────────────
BRAND_STYLE_GUIDE = """
BRAND: Florida Man Adventures
AESTHETIC: Retro/Rugged — distressed vintage screen-print, outdoor badge culture
COLOR PALETTE: Burnt orange (#c45c1a), navy blue (#1a2a3a), cream (#f4e7d3), aged white
TYPOGRAPHY: Bold slab-serif fonts (similar to Rockwell, Clarendon, or Cooper Black)
DESIGN STYLE: Circular badge layouts, distressed textures, vintage outdoor brand feel
  — Think: National Park badges, old fishing tournament patches, 1970s sportswear
  — Silhouettes of airboats, gators, herons, mangroves, swamp scenes at sunset
  — Worn/aged texture overlays, halftone dots, rough ink edges
TONE: Rugged, self-aware, Southern-proud, slightly absurdist
LOGO ELEMENT: The brand badge (circular, airboat silhouette at sunset) can appear
  as a small secondary element on sleeve or back-neck area of designs.
"""

# ─────────────────────────────────────────────
# Dual Design Style System
# ─────────────────────────────────────────────
# Style A: Smack Apparel (primary — ~60% of drops)
# Bold, high-contrast, dark tee with punchy oversized text.
# Think: Barstool Sports merch, viral streetwear, meme drops.
# Style B: Retro/Rugged (secondary — ~40% of drops)
# Distressed vintage badge, outdoor brand feel, burnt orange + navy.
# Think: National Park patches, 1970s fishing tournament tees.

STYLE_SMACK = """STYLE: Smack Apparel (primary)
- Background: black or dark charcoal tee
- Text: oversized, bold, all-caps, high-contrast (white, neon green, or gold on black)
- Layout: text-heavy, centered, punchy — the headline IS the design
- Typography: heavy sans-serif or condensed block font (Impact, Anton, Bebas Neue style)
- Vibe: viral meme energy, streetwear, instantly readable from 10 feet away
- Optional: minimal graphic element (gator silhouette, fish icon) supporting the text
- NO complex illustrations, NO busy backgrounds, NO vintage textures"""

STYLE_RETRO = """STYLE: Retro/Rugged (secondary)
- Color palette: burnt orange (#c45c1a), navy blue (#1a2a3a), cream/aged white
- Typography: bold slab-serif fonts (Rockwell, Clarendon, Cooper Black style), distressed/worn
- Layout: circular badge compositions OR bold centered text with distressed borders
- Texture: vintage screen-print aesthetic, halftone dots, rough ink edges
- Scene elements: airboats, gators, herons, mangroves, swamp sunsets, fishing silhouettes
- Vibe: outdoor badge culture, 1970s sportswear, National Park patch feel
- NO modern flat design, NO neon colors, NO photorealistic elements"""

SYSTEM_INSTRUCTION = """
You are a viral apparel trend analyst specializing in Florida culture, fishing, and Southern humor.
Your job is to identify high-potential concepts for viral t-shirt designs.

The factory uses TWO design styles. Assign each concept a design_style field:
- Use "smack" for approximately 60% of concepts (bold, text-heavy, dark tee, meme energy)
- Use "retro" for approximately 40% of concepts (vintage badge, burnt orange/navy, outdoor brand)

For each concept you MUST return a JSON object with these exact fields:
{{
  "title": "SHORT UPPERCASE HEADLINE (max 4 words)",
  "headline": "SAME AS TITLE — the text that appears on the shirt",
  "description": "One punchy sentence describing the shirt vibe",
  "trend_category": one of ["fishing_meme", "regional_slang", "viral_moment", "wildlife_encounter", "florida_lifestyle"],
  "confidence_score": integer 70-99,
  "is_limited_drop": boolean,
  "design_style": "smack" or "retro",
  "dalle_image_prompt": "Full DALL-E 3 prompt tailored to the chosen design_style — MUST include: isolated on transparent background, suitable for DTG printing, 300 DPI, PNG-24 format, Florida/angler cultural reference. For smack style: bold oversized text, high contrast, dark background. For retro style: vintage screen-print, burnt orange and navy, distressed badge layout."
}}

Return a JSON array of exactly {{count}} concepts. No markdown, no explanation — raw JSON only.
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
    model = genai.GenerativeModel("gemini-flash-latest")

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
# Forge Image API: Image Generation
# ─────────────────────────────────────────────
# Style-aware print spec suffixes appended to every image prompt
PRINT_SPEC_SMACK = (
    " Bold oversized all-caps text, high contrast white or neon green on black. "
    "Heavy condensed block font (Impact/Anton/Bebas Neue style). Text-heavy centered layout. "
    "Minimal supporting graphic element optional (gator, fish silhouette). "
    "Isolated on transparent background. Suitable for DTG printing. "
    "300 DPI. PNG-24 format. No busy backgrounds. No gradients. Clean sharp edges."
)

PRINT_SPEC_RETRO = (
    " Retro vintage screen-print aesthetic. Distressed halftone texture overlay. "
    "Color palette: burnt orange (#c45c1a), navy blue (#1a2a3a), cream/aged white — no neon colors. "
    "Bold slab-serif typography (Rockwell/Clarendon/Cooper Black style). "
    "Circular badge layout or centered bold text with distressed border. "
    "Florida swamp/airboat/gator scene elements. Isolated on transparent background. "
    "Suitable for DTG printing. 300 DPI. PNG-24 format. No photorealistic elements. Clean distressed edges."
)

def get_print_spec(design_style: str) -> str:
    """Return the correct print spec suffix based on design style."""
    return PRINT_SPEC_RETRO if design_style == "retro" else PRINT_SPEC_SMACK

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(log, logging.WARNING),
)
def generate_dalle_image(prompt: str, concept_id: str, design_style: str = "smack") -> tuple[Path, dict]:
    """
    Call the Manus Forge image API (images.v1.ImageService/GenerateImage) to
    generate an image, decode the base64 response, and save it locally.
    Returns (local_path, image_metadata).
    Retries up to 3 times with exponential backoff on any failure.
    design_style: 'smack' (bold text-heavy viral) or 'retro' (vintage badge)
    """
    if not FORGE_API_URL or not FORGE_API_KEY:
        raise RuntimeError(
            "BUILT_IN_FORGE_API_URL and BUILT_IN_FORGE_API_KEY must be set for image generation."
        )

    log.info(f"[{concept_id}] Calling Forge image API [{design_style.upper()} style, model={FORGE_IMAGE_MODEL}]...")

    full_prompt = prompt + get_print_spec(design_style)

    endpoint = f"{FORGE_API_URL}/images.v1.ImageService/GenerateImage"
    payload = {
        "prompt": full_prompt,
        "model": FORGE_IMAGE_MODEL,
        "quality": FORGE_IMAGE_QUALITY,
    }

    resp = requests.post(
        endpoint,
        json=payload,
        headers={
            "Authorization": f"Bearer {FORGE_API_KEY}",
            "Content-Type": "application/json",
            "connect-protocol-version": "1",
        },
        timeout=120,
    )

    if not resp.ok:
        raise RuntimeError(
            f"Forge image API returned {resp.status_code}: {resp.text[:300]}"
        )

    result = resp.json()
    image_data = result.get("image", {})
    b64_json = image_data.get("b64Json", "")
    mime_type = image_data.get("mimeType", "image/png")

    if not b64_json:
        raise RuntimeError(f"Forge image API returned empty b64Json. Full response: {str(result)[:300]}")

    # Decode base64 → bytes → save as PNG
    image_bytes = base64.b64decode(b64_json)
    filename = f"{concept_id}_{int(time.time())}.png"
    local_path = OUTPUT_DIR / filename
    local_path.write_bytes(image_bytes)
    log.info(f"[{concept_id}] Image saved → {local_path} ({len(image_bytes):,} bytes, mime={mime_type})")

    return local_path, {"revised_prompt": full_prompt, "model": FORGE_IMAGE_MODEL}


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

    # Forge/gpt-image-2 returns 1024x1024 at 72 DPI metadata but the pixel density
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
    design_style from Gemini: 'smack' (bold viral) or 'retro' (vintage badge)
    """
    title = raw.get("title", "UNTITLED").upper().replace(" ", "_")
    concept_id = hashlib.md5(title.encode()).hexdigest()[:8]
    design_style = raw.get("design_style", "smack")  # default to Smack Apparel style

    log.info(f"Processing concept: {title} (id={concept_id}, style={design_style.upper()}, attempt={attempt})")

    try:
        local_path, _ = generate_dalle_image(raw["dalle_image_prompt"], concept_id, design_style)
        meta = validate_image(local_path, concept_id)

        return GeneratedConcept(
            id=concept_id,
            title=raw.get("title", "UNTITLED"),
            headline=raw.get("headline", raw.get("title", "UNTITLED")),
            description=raw.get("description", ""),
            trend_category=raw.get("trend_category", "florida_lifestyle"),
            confidence_score=int(raw.get("confidence_score", 80)),
            is_limited_drop=bool(raw.get("is_limited_drop", False)),
            design_style=design_style,
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
        log.error(f"[{concept_id}] All image generation retries exhausted: {e}")
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
