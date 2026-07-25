#!/usr/bin/env python3
"""
FLORIDA MAN DROPS — GENERATION PHASE
Detects viral trends via Gemini, generates DALL-E 3 designs with print specifications.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential

# Configure logging
log = logging.getLogger(__name__)

# Try new google-genai first, fall back to deprecated google-generativeai
try:
    from google import genai
    USE_NEW_GENAI = True
except ImportError:
    import google.generativeai as genai
    USE_NEW_GENAI = False

from openai import OpenAI, BadRequestError

SYSTEM_INSTRUCTION = """You are a viral trend detection AI for Florida Man t-shirt designs.
Detect the MOST VIRAL micro-trends happening RIGHT NOW in Florida culture, memes, and internet culture.

For each trend, return JSON with:
- trend_name: Short catchy name (e.g., "SWAMP TAX COLLECTOR")
- product_description: 1-2 sentence description
- dalle_image_prompt: Detailed DALL-E 3 prompt for t-shirt design
- confidence_score: 0-100 confidence this will go viral
- trend_category: MEME, FLORIDA_CULTURE, INTERNET_SLANG, SPORTS, POLITICS, NATURE, or OTHER
- print_specifications: {dpi: 300, format: "PNG-24", background: "transparent", dimensions: "3600x4800", style: "minimalist vector art, high contrast, text-heavy"}

Return ONLY valid JSON array. No markdown, no code blocks."""

RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "trend_name": {"type": "string"},
            "product_description": {"type": "string"},
            "dalle_image_prompt": {"type": "string"},
            "confidence_score": {"type": "number"},
            "trend_category": {"type": "string"},
            "print_specifications": {
                "type": "object",
                "properties": {
                    "dpi": {"type": "number"},
                    "format": {"type": "string"},
                    "background": {"type": "string"},
                    "dimensions": {"type": "string"},
                    "style": {"type": "string"}
                }
            }
        },
        "required": ["trend_name", "product_description", "dalle_image_prompt", "confidence_score", "trend_category", "print_specifications"]
    }
}

DESIGN_STYLES = ["SMACK", "RETRO"]

def detect_viral_trends(count: int = 1) -> list:
    """Detect viral trends via Gemini."""
    log.info(f"Detecting {count} viral trends via Gemini...")
    
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        raise ValueError("GEMINI_API_KEY not set")
    
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    
    try:
        if USE_NEW_GENAI:
            client = genai.Client(api_key=gemini_key)
            response = client.models.generate_content(
                model=gemini_model,
                contents=SYSTEM_INSTRUCTION,
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=RESPONSE_SCHEMA,
                )
            )
            text = response.text
        else:
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel(gemini_model)
            response = model.generate_content(
                SYSTEM_INSTRUCTION,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=RESPONSE_SCHEMA,
                )
            )
            text = response.text
        
        concepts = json.loads(text)
        log.info(f"Gemini returned {len(concepts)} concepts")
        return concepts
    except Exception as e:
        log.error(f"Gemini trend detection failed: {e}")
        raise

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def generate_dalle_image(prompt: str, concept_id: str, style: str) -> Optional[str]:
    """Generate DALL-E 3 image. FIXED: Removed response_format parameter."""
    log.info(f"[{concept_id}] Calling DALL-E 3 via OpenAI [{style} style]...")
    
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        raise ValueError("OPENAI_API_KEY not set")
    
    client = OpenAI(api_key=openai_key)
    
    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1
        )
        
        image_url = response.data[0].url
        log.info(f"[{concept_id}] Image generated: {image_url}")
        return image_url
    except BadRequestError as e:
        log.warning(f"Retrying generate_dalle_image as it raised BadRequestError: {e}")
        raise
    except Exception as e:
        log.error(f"[{concept_id}] DALL-E 3 generation failed: {e}")
        raise

def generate_designs(count: int = 1, output_file: str = "output/generated_concepts.json") -> list:
    """Generate viral t-shirt designs."""
    log.info("=" * 60)
    log.info("FLORIDA MAN DROPS — GENERATION PHASE STARTED")
    log.info("=" * 60)
    
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    
    concepts = detect_viral_trends(count)
    
    saved_concepts = []
    for idx, concept in enumerate(concepts, 1):
        concept_id = concept.get("trend_name", f"concept_{idx}").upper().replace(" ", "_")[:16]
        style = DESIGN_STYLES[idx % len(DESIGN_STYLES)]
        
        log.info(f"--- Concept {idx}/{len(concepts)}: {concept.get('trend_name')} ---")
        log.info(f"Processing concept: {concept_id} (id={concept_id[:8]}, style={style}, attempt=1)")
        
        try:
            image_url = generate_dalle_image(
                prompt=concept.get("dalle_image_prompt"),
                concept_id=concept_id[:8],
                style=style
            )
            
            concept["image_url"] = image_url
            concept["generated_at"] = datetime.utcnow().isoformat()
            concept["style"] = style
            
            saved_concepts.append(concept)
            log.info(f"✓ Concept {idx} saved")
        except Exception as e:
            log.warning(f"✗ Skipped concept {idx} after all retries failed: {e}")
            continue
    
    with open(output_file, "w") as f:
        json.dump(saved_concepts, f, indent=2)
    
    log.info(f"Saved {len(saved_concepts)}/{len(concepts)} concepts → {output_file}")
    log.info("=" * 60)
    log.info(f"GENERATION PHASE COMPLETE — {len(saved_concepts)} concepts ready")
    log.info("=" * 60)
    
    return saved_concepts

def run(count: int = 1) -> list:
    """Wrapper function for main.py compatibility."""
    return generate_designs(count)
