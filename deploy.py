"""
deploy.py — Florida Man Drops Automation Factory
==================================================
Phase 4: Storefront Sync & Post-Deployment Reporting

Responsibilities:
  1. Load deployed_products.json from upload phase
  2. Sync product data to the storefront (writes storefront_products.json)
  3. Update the "daily drop" hero product (highest confidence score)
  4. Archive products older than 7 days to the archive section
  5. Generate a deployment report with full pipeline summary
  6. Send optional webhook notification on successful deployment

Uses tenacity for retry on file I/O and webhook calls.
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
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
log = logging.getLogger("deploy")

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
DEPLOYED_FILE           = Path(os.getenv("DEPLOYED_FILE", "output/deployed_products.json"))
APPROVED_FILE           = Path(os.getenv("APPROVED_FILE", "output/approved_catalog.json"))
STOREFRONT_FILE         = Path(os.getenv("STOREFRONT_FILE", "output/storefront_products.json"))
REPORT_FILE             = Path(os.getenv("REPORT_FILE", "output/deployment_report.json"))
STOREFRONT_URL          = os.getenv("STOREFRONT_URL", "https://www.floridamanadventures.com")
WEBHOOK_URL             = os.getenv("DEPLOY_WEBHOOK_URL", "")   # Optional: POST notification on deploy
ARCHIVE_AFTER_DAYS      = int(os.getenv("ARCHIVE_AFTER_DAYS", "7"))
DEFAULT_PRICE           = float(os.getenv("DEFAULT_PRICE", "29.99"))
LIMITED_DROP_PRICE      = float(os.getenv("LIMITED_DROP_PRICE", "34.99"))

STOREFRONT_FILE.parent.mkdir(parents=True, exist_ok=True)
REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────
@dataclass
class StorefrontProduct:
    id: str
    title: str
    headline: str
    description: str
    trend_category: str
    confidence_score: int
    is_limited_drop: bool
    price: float
    mockup_url: str
    printful_sync_product_id: int
    buy_url: str
    deployed_at: str
    is_hero: bool
    is_archived: bool


@dataclass
class DeploymentReport:
    run_at: str
    total_generated: int
    total_approved: int
    total_deployed: int
    hero_product: str
    storefront_url: str
    products: list


# ─────────────────────────────────────────────
# Storefront Sync
# ─────────────────────────────────────────────
def build_storefront_products(
    deployed: list[dict],
    approved_map: dict,
) -> list[StorefrontProduct]:
    """
    Merge deployed product data with catalog metadata to build
    the full storefront product list.
    """
    now = datetime.utcnow()
    archive_cutoff = now - timedelta(days=ARCHIVE_AFTER_DAYS)

    products = []
    for d in deployed:
        concept_id = d["concept_id"]
        meta = approved_map.get(concept_id, {})

        deployed_at_str = d.get("deployed_at", now.isoformat())
        try:
            deployed_at = datetime.fromisoformat(deployed_at_str)
        except ValueError:
            deployed_at = now

        is_archived = deployed_at < archive_cutoff
        is_limited = meta.get("is_limited_drop", False)
        price = LIMITED_DROP_PRICE if is_limited else DEFAULT_PRICE

        # Generate tracking buy URL
        buy_url = (
            f"{STOREFRONT_URL}/redirect"
            f"?id={concept_id}"
            f"&source=storefront_sync"
            f"&printful_id={d['printful_sync_product_id']}"
        )

        products.append(
            StorefrontProduct(
                id=concept_id,
                title=d["title"],
                headline=meta.get("headline", d["title"]),
                description=meta.get("description", ""),
                trend_category=meta.get("trend_category", "florida_lifestyle"),
                confidence_score=meta.get("confidence_score", 80),
                is_limited_drop=is_limited,
                price=price,
                mockup_url=d["mockup_url"],
                printful_sync_product_id=d["printful_sync_product_id"],
                buy_url=buy_url,
                deployed_at=deployed_at_str,
                is_hero=False,   # Set below
                is_archived=is_archived,
            )
        )

    # Mark the highest-confidence non-archived product as hero
    active = [p for p in products if not p.is_archived]
    if active:
        hero = max(active, key=lambda p: p.confidence_score)
        hero.is_hero = True
        log.info(f"Hero product: {hero.title} (confidence={hero.confidence_score})")

    return products


def load_approved_map() -> dict:
    """Load approved_catalog.json and return a dict keyed by concept id."""
    if not APPROVED_FILE.exists():
        log.warning(f"Approved catalog not found: {APPROVED_FILE}")
        return {}
    approved = json.loads(APPROVED_FILE.read_text())
    return {entry["id"]: entry for entry in approved}


# ─────────────────────────────────────────────
# Webhook Notification
# ─────────────────────────────────────────────
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=15),
    retry=retry_if_exception_type(requests.RequestException),
    before_sleep=before_sleep_log(log, logging.WARNING),
)
def send_webhook_notification(report: dict) -> None:
    """
    POST deployment report to DEPLOY_WEBHOOK_URL if configured.
    Retries up to 3 times on network errors.
    """
    if not WEBHOOK_URL:
        return

    log.info(f"Sending webhook notification to {WEBHOOK_URL}...")
    response = requests.post(
        WEBHOOK_URL,
        json={
            "event": "florida_man_drops.deployment_complete",
            "timestamp": datetime.utcnow().isoformat(),
            "data": report,
        },
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    response.raise_for_status()
    log.info(f"Webhook delivered — status: {response.status_code}")


# ─────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────
def run(
    generated_count: int = 0,
    approved_count: int = 0,
) -> Optional[DeploymentReport]:
    """
    Full deploy phase:
    1. Load deployed products
    2. Merge with catalog metadata
    3. Build storefront product list
    4. Save storefront_products.json
    5. Generate deployment report
    6. Send webhook notification (if configured)
    Returns DeploymentReport or None on failure.
    """
    log.info("=" * 60)
    log.info("FLORIDA MAN DROPS — DEPLOY PHASE STARTED")
    log.info("=" * 60)

    if not DEPLOYED_FILE.exists():
        log.error(f"Deployed products file not found: {DEPLOYED_FILE}")
        log.error("Run upload.py first to deploy products to Printful.")
        return None

    deployed = json.loads(DEPLOYED_FILE.read_text())
    approved_map = load_approved_map()

    log.info(f"Loaded {len(deployed)} deployed products")

    # Build storefront product list
    products = build_storefront_products(deployed, approved_map)
    active = [p for p in products if not p.is_archived]
    archived = [p for p in products if p.is_archived]

    log.info(f"Storefront: {len(active)} active, {len(archived)} archived")

    # Save storefront products
    STOREFRONT_FILE.write_text(
        json.dumps([asdict(p) for p in products], indent=2)
    )
    log.info(f"Storefront products → {STOREFRONT_FILE}")

    # Build report
    hero = next((p for p in products if p.is_hero), None)
    report = DeploymentReport(
        run_at=datetime.utcnow().isoformat(),
        total_generated=generated_count,
        total_approved=approved_count,
        total_deployed=len(deployed),
        hero_product=hero.title if hero else "None",
        storefront_url=STOREFRONT_URL,
        products=[
            {
                "id": p.id,
                "title": p.title,
                "price": p.price,
                "is_hero": p.is_hero,
                "is_archived": p.is_archived,
                "buy_url": p.buy_url,
                "mockup_url": p.mockup_url,
            }
            for p in products
        ],
    )

    REPORT_FILE.write_text(json.dumps(asdict(report), indent=2))
    log.info(f"Deployment report → {REPORT_FILE}")

    # Send webhook
    try:
        send_webhook_notification(asdict(report))
    except RetryError as e:
        log.warning(f"Webhook notification failed (non-blocking): {e}")

    log.info("=" * 60)
    log.info(f"DEPLOY PHASE COMPLETE")
    log.info(f"  Hero: {report.hero_product}")
    log.info(f"  Active products: {len(active)}")
    log.info(f"  Storefront: {STOREFRONT_URL}")
    log.info("=" * 60)
    return report


if __name__ == "__main__":
    report = run()
    if report:
        print(f"\nDeployment complete:")
        print(f"  Hero: {report.hero_product}")
        print(f"  Products: {report.total_deployed}")
        print(f"  Report: {REPORT_FILE}")
