"""
upload.py — Florida Man Drops Automation Factory
==================================================
Phase 3: Printful API Integration — File Upload, Product Creation & Mockup Generation

Responsibilities:
  1. Load approved concepts from approved_catalog.json
  2. Upload each print-ready PNG to Printful /files endpoint (Bearer auth)
  3. Create a Printful product with correct print_area placement (front center, 12x16 in)
  4. Generate mockup images for the product
  5. Save deployed product data to deployed_products.json
  6. All API calls use tenacity retry with exponential backoff

Printful API v2 — Bearer token authentication required.
"""

import os
import json
import logging
import time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

import requests
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
log = logging.getLogger("upload")

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
PRINTFUL_API_KEY    = os.getenv("PRINTFUL_API_KEY", "")
PRINTFUL_BASE_URL   = "https://api.printful.com"
APPROVED_FILE       = Path(os.getenv("APPROVED_FILE", "output/approved_catalog.json"))
DEPLOYED_FILE       = Path(os.getenv("DEPLOYED_FILE", "output/deployed_products.json"))
STORE_ID            = os.getenv("PRINTFUL_STORE_ID", "")   # Optional: scope to specific store

# Printful product config — Bella + Canvas 3001 Unisex Jersey Short Sleeve Tee
PRINTFUL_PRODUCT_ID = int(os.getenv("PRINTFUL_PRODUCT_ID", "71"))
# Black variants: S=4011, M=4012, L=4013, XL=4014, 2XL=4015
DEFAULT_VARIANTS    = [4011, 4012, 4013, 4014, 4015]

# Print area: front center, 12x16 inches at 300 DPI
PRINT_AREA_WIDTH    = float(os.getenv("PRINT_AREA_WIDTH", "12"))    # inches
PRINT_AREA_HEIGHT   = float(os.getenv("PRINT_AREA_HEIGHT", "16"))   # inches
PRINT_AREA_TOP      = float(os.getenv("PRINT_AREA_TOP", "2"))       # inches from top
PRINT_AREA_LEFT     = float(os.getenv("PRINT_AREA_LEFT", "4.25"))   # inches from left (center on 12.5in shirt)

DEPLOYED_FILE.parent.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────
@dataclass
class DeployedProduct:
    concept_id: str
    title: str
    printful_file_id: int
    printful_file_url: str
    printful_product_id: int
    printful_sync_product_id: int
    mockup_url: str
    deployed_at: str
    variants: list


# ─────────────────────────────────────────────
# Printful API Helpers
# ─────────────────────────────────────────────
def _headers() -> dict:
    """Return Printful API headers with Bearer token auth."""
    headers = {
        "Authorization": f"Bearer {PRINTFUL_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if STORE_ID:
        headers["X-PF-Store-Id"] = STORE_ID
    return headers


def _handle_response(response: requests.Response, context: str) -> dict:
    """Check response status and return JSON. Raises on error."""
    if response.status_code in (200, 201):
        return response.json()
    log.error(
        f"[{context}] Printful API error {response.status_code}: {response.text[:500]}"
    )
    response.raise_for_status()
    return {}


# ─────────────────────────────────────────────
# Step 1: Upload File to Printful
# ─────────────────────────────────────────────
@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=3, max=30),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(log, logging.WARNING),
)
def upload_file_to_printful(image_path: Path, concept_id: str) -> tuple[int, str]:
    """
    Upload a PNG file to Printful's /files endpoint.
    Returns (file_id, file_url) — the permanent Printful-hosted URL.
    Retries up to 4 times with exponential backoff.
    """
    log.info(f"[{concept_id}] Uploading file to Printful: {image_path.name}")

    with open(image_path, "rb") as f:
        file_data = f.read()

    # Printful file upload uses multipart form data
    upload_response = requests.post(
        f"{PRINTFUL_BASE_URL}/files",
        headers={
            "Authorization": f"Bearer {PRINTFUL_API_KEY}",
            **({"X-PF-Store-Id": STORE_ID} if STORE_ID else {}),
        },
        files={
            "file": (image_path.name, file_data, "image/png"),
        },
        data={
            "type": "default",
            "filename": image_path.name,
        },
        timeout=120,
    )

    result = _handle_response(upload_response, concept_id)
    file_id = result["result"]["id"]
    file_url = result["result"]["url"]
    log.info(f"[{concept_id}] File uploaded — ID: {file_id}, URL: {file_url}")
    return file_id, file_url


# ─────────────────────────────────────────────
# Step 2: Create Printful Product
# ─────────────────────────────────────────────
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(log, logging.WARNING),
)
def create_printful_product(
    concept: dict,
    file_id: int,
    file_url: str,
) -> dict:
    """
    Create a sync product in Printful with the uploaded design file.
    Uses print_area placement: front center, 12x16 inches.
    Returns the full Printful sync product response.
    Retries up to 3 times.
    """
    concept_id = concept["id"]
    title = concept["title"]
    log.info(f"[{concept_id}] Creating Printful product: {title}")

    # Build variant list with the design file applied to each
    sync_variants = []
    for variant_id in DEFAULT_VARIANTS:
        sync_variants.append({
            "variant_id": variant_id,
            "retail_price": "29.99",
            "files": [
                {
                    "type": "front",
                    "id": file_id,
                    "position": {
                        "area_width": PRINT_AREA_WIDTH,
                        "area_height": PRINT_AREA_HEIGHT,
                        "width": PRINT_AREA_WIDTH,
                        "height": PRINT_AREA_HEIGHT,
                        "top": PRINT_AREA_TOP,
                        "left": PRINT_AREA_LEFT,
                    },
                }
            ],
        })

    payload = {
        "sync_product": {
            "name": title,
            "description": concept.get("description", ""),
            "thumbnail": file_url,
        },
        "sync_variants": sync_variants,
    }

    response = requests.post(
        f"{PRINTFUL_BASE_URL}/store/products",
        headers=_headers(),
        json=payload,
        timeout=60,
    )

    result = _handle_response(response, concept_id)
    sync_product_id = result["result"]["id"]
    log.info(f"[{concept_id}] Product created — sync product ID: {sync_product_id}")
    return result["result"]


# ─────────────────────────────────────────────
# Step 3: Generate Mockup
# ─────────────────────────────────────────────
@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=3, min=5, max=60),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(log, logging.WARNING),
)
def generate_mockup(
    concept_id: str,
    file_url: str,
    variant_id: int = 4013,  # Default: L (most common for mockup photos)
) -> str:
    """
    Submit a mockup generation task to Printful and poll until complete.
    Returns the mockup image URL.
    Retries up to 4 times on failure.
    """
    log.info(f"[{concept_id}] Submitting mockup generation task...")

    payload = {
        "variant_ids": [variant_id],
        "format": "jpg",
        "files": [
            {
                "placement": "front",
                "image_url": file_url,
                "position": {
                    "area_width": PRINT_AREA_WIDTH,
                    "area_height": PRINT_AREA_HEIGHT,
                    "width": PRINT_AREA_WIDTH,
                    "height": PRINT_AREA_HEIGHT,
                    "top": PRINT_AREA_TOP,
                    "left": PRINT_AREA_LEFT,
                },
            }
        ],
    }

    response = requests.post(
        f"{PRINTFUL_BASE_URL}/mockup-generator/create-task/{PRINTFUL_PRODUCT_ID}",
        headers=_headers(),
        json=payload,
        timeout=30,
    )
    result = _handle_response(response, concept_id)
    task_key = result["result"]["task_key"]
    log.info(f"[{concept_id}] Mockup task submitted — key: {task_key}")

    # Poll for completion (max 60 seconds)
    for attempt in range(20):
        time.sleep(3)
        poll_response = requests.get(
            f"{PRINTFUL_BASE_URL}/mockup-generator/task?task_key={task_key}",
            headers=_headers(),
            timeout=15,
        )
        poll_result = _handle_response(poll_response, concept_id)
        status = poll_result["result"]["status"]

        if status == "completed":
            mockups = poll_result["result"].get("mockups", [])
            if mockups:
                mockup_url = mockups[0]["mockup_url"]
                log.info(f"[{concept_id}] Mockup ready → {mockup_url}")
                return mockup_url
            raise ValueError(f"[{concept_id}] Mockup task completed but no mockup URLs returned")

        elif status == "failed":
            raise RuntimeError(
                f"[{concept_id}] Mockup generation failed: {poll_result['result'].get('error', 'Unknown error')}"
            )

        log.info(f"[{concept_id}] Mockup status: {status} (attempt {attempt+1}/20)")

    raise TimeoutError(f"[{concept_id}] Mockup generation timed out after 60 seconds")


# ─────────────────────────────────────────────
# Core: Deploy One Concept
# ─────────────────────────────────────────────
def deploy_concept(concept: dict) -> Optional[DeployedProduct]:
    """
    Full deployment pipeline for one concept:
    1. Upload PNG to Printful /files
    2. Create sync product with print_area placement
    3. Generate mockup
    Returns DeployedProduct or None on failure.
    """
    concept_id = concept["id"]
    title = concept["title"]
    print_ready_path = Path(concept["print_ready_path"])

    log.info(f"[{concept_id}] Deploying: {title}")

    try:
        # Step 1: Upload file
        file_id, file_url = upload_file_to_printful(print_ready_path, concept_id)

        # Step 2: Create product
        product_result = create_printful_product(concept, file_id, file_url)
        sync_product_id = product_result["id"]

        # Step 3: Generate mockup
        try:
            mockup_url = generate_mockup(concept_id, file_url)
        except (RetryError, TimeoutError, RuntimeError) as e:
            log.warning(f"[{concept_id}] Mockup generation failed (non-blocking): {e}")
            mockup_url = file_url  # Fall back to the raw design URL

        deployed = DeployedProduct(
            concept_id=concept_id,
            title=title,
            printful_file_id=file_id,
            printful_file_url=file_url,
            printful_product_id=PRINTFUL_PRODUCT_ID,
            printful_sync_product_id=sync_product_id,
            mockup_url=mockup_url,
            deployed_at=datetime.utcnow().isoformat(),
            variants=DEFAULT_VARIANTS,
        )

        log.info(f"[{concept_id}] ✓ DEPLOYED: {title} (sync_id={sync_product_id})")
        return deployed

    except RetryError as e:
        log.error(f"[{concept_id}] All retries exhausted for {title}: {e}")
        return None
    except Exception as e:
        log.error(f"[{concept_id}] Deployment failed for {title}: {e}")
        return None


# ─────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────
def run() -> list[DeployedProduct]:
    """
    Full upload phase:
    1. Load approved_catalog.json
    2. Deploy each concept to Printful
    3. Save deployed_products.json
    Returns list of successfully deployed products.
    """
    log.info("=" * 60)
    log.info("FLORIDA MAN DROPS — UPLOAD PHASE STARTED")
    log.info("=" * 60)

    if not APPROVED_FILE.exists():
        log.error(f"Approved catalog not found: {APPROVED_FILE}")
        log.error("Run catalog.py first to approve concepts.")
        return []

    if not PRINTFUL_API_KEY:
        log.error("PRINTFUL_API_KEY environment variable is not set.")
        return []

    approved = json.loads(APPROVED_FILE.read_text())
    log.info(f"Loaded {len(approved)} approved concepts from {APPROVED_FILE}")

    deployed: list[DeployedProduct] = []

    for i, concept in enumerate(approved):
        log.info(f"--- Deploying {i+1}/{len(approved)}: {concept.get('title', '?')} ---")
        result = deploy_concept(concept)
        if result:
            deployed.append(result)
        else:
            log.warning(f"Skipped concept {i+1}: {concept.get('title', '?')}")

        # Rate limiting: 1 second between deployments
        if i < len(approved) - 1:
            time.sleep(1)

    # Save results
    DEPLOYED_FILE.write_text(json.dumps([asdict(d) for d in deployed], indent=2))
    log.info(f"Deployed {len(deployed)}/{len(approved)} products → {DEPLOYED_FILE}")

    log.info("=" * 60)
    log.info(f"UPLOAD PHASE COMPLETE — {len(deployed)} products live on Printful")
    log.info("=" * 60)
    return deployed


if __name__ == "__main__":
    products = run()
    print(f"\nDeployed {len(products)} products to Printful:")
    for p in products:
        print(f"  {p.title} — sync_id={p.printful_sync_product_id}, mockup={p.mockup_url}")
