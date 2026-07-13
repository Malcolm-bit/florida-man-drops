"""
main.py — Florida Man Drops Automation Factory
================================================
Master Controller — Orchestrates the Full Automation Pipeline

Pipeline Stages:
  1. GENERATE  — Detect viral trends + generate images (generate.py)
  2. CATALOG   — Validate images with Pillow + approve concepts (catalog.py)
  3. UPLOAD    — Upload to Printful + create products + generate mockups (upload.py)
  4. DEPLOY    — Sync to storefront + generate deployment report (deploy.py)

Usage:
  python3 main.py                              # Run full pipeline
  python3 main.py --stage generate             # Run only generation phase
  python3 main.py --stage catalog              # Run only catalog phase
  python3 main.py --stage upload               # Run only upload phase
  python3 main.py --stage deploy               # Run only deploy phase
  python3 main.py --count 3                    # Generate 3 concepts (default: 5)
  python3 main.py --dry-run                    # Validate env + imports only
  python3 main.py --image-provider openai      # Use DALL-E 3 via OpenAI API key
  python3 main.py --image-provider forge       # Use Forge image API (default)

Environment Variables Required:
  GEMINI_API_KEY      — Viral trend detection
  PRINTFUL_API_KEY    — Printful Bearer token (OAuth 2.0)

  For --image-provider openai (default on Termux / external machines):
    OPENAI_API_KEY    — DALL-E 3 image generation (platform.openai.com/api-keys)

  For --image-provider forge (default in Manus sandbox):
    BUILT_IN_FORGE_API_URL  — Manus Forge base URL
    BUILT_IN_FORGE_API_KEY  — Manus Forge bearer token

Optional:
  PRINTFUL_STORE_ID   — Scope to specific Printful store
  MAX_CONCEPTS        — Number of concepts to generate (default: 5)
  MIN_CONFIDENCE      — Minimum confidence score to approve (default: 75)
  OUTPUT_DIR          — Directory for generated images (default: output/images)
  FORGE_IMAGE_MODEL   — Forge model enum (default: MODEL_GPT_IMAGE_2)
  FORGE_IMAGE_QUALITY — Forge quality (default: high)
  DEPLOY_WEBHOOK_URL  — POST notification URL on successful deployment
"""

import os
import sys
import json
import logging
import argparse
import traceback
from pathlib import Path
from datetime import datetime

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("output/pipeline.log", mode="a"),
    ],
)
log = logging.getLogger("main")

# ─────────────────────────────────────────────
# Required Environment Variables
# ─────────────────────────────────────────────
REQUIRED_ENV_VARS_ALWAYS = {
    "GEMINI_API_KEY":   "Viral trend detection (get from aistudio.google.com/apikey)",
    "PRINTFUL_API_KEY": "Printful Bearer token (get from developers.printful.com → Private token)",
}
REQUIRED_ENV_VARS_OPENAI = {
    "OPENAI_API_KEY":   "DALL-E 3 image generation (get from platform.openai.com/api-keys)",
}
REQUIRED_ENV_VARS_FORGE = {
    "BUILT_IN_FORGE_API_URL": "Manus Forge base URL",
    "BUILT_IN_FORGE_API_KEY": "Manus Forge bearer token",
}

def check_environment(image_provider: str = "forge") -> bool:
    """Validate all required environment variables are set. Returns True if OK."""
    provider_vars = REQUIRED_ENV_VARS_OPENAI if image_provider == "openai" else REQUIRED_ENV_VARS_FORGE
    all_required = {**REQUIRED_ENV_VARS_ALWAYS, **provider_vars}
    missing = []
    for var, description in all_required.items():
        if not os.getenv(var):
            missing.append(f"  {var}: {description}")
    if missing:
        log.error("Missing required environment variables:")
        for m in missing:
            log.error(m)
        if image_provider == "openai":
            log.error("\nFor OpenAI image provider, set:")
            log.error("  export OPENAI_API_KEY=sk-...")
        else:
            log.error("\nFor Forge image provider, set:")
            log.error("  export BUILT_IN_FORGE_API_URL=https://forge.manus.ai")
            log.error("  export BUILT_IN_FORGE_API_KEY=your_forge_key")
        log.error("  export GEMINI_API_KEY=AIza...")
        log.error("  export PRINTFUL_API_KEY=your_bearer_token")
        return False
    log.info("Environment check passed — all required variables set")
    return True


def check_dependencies() -> bool:
    """Verify all required Python packages are installed."""
    required = {
        "openai": "pip install openai",
        "PIL": "pip install Pillow",
        "google.generativeai": "pip install google-generativeai",
        "tenacity": "pip install tenacity",
        "requests": "pip install requests",
    }
    missing = []
    for module, install_cmd in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(f"  {module}: {install_cmd}")

    if missing:
        log.error("Missing Python packages:")
        for m in missing:
            log.error(m)
        log.error("\nInstall all dependencies:")
        log.error("  pip install openai Pillow google-generativeai tenacity requests")
        return False

    log.info("Dependency check passed — all packages available")
    return True


# ─────────────────────────────────────────────
# Pipeline Stages
# ─────────────────────────────────────────────
def stage_generate(count: int) -> list:
    """Run Phase 1: Trend detection + DALL-E 3 image generation."""
    log.info("▶ STAGE 1: GENERATE")
    import generate
    concepts = generate.run(count=count)
    log.info(f"✓ STAGE 1 COMPLETE — {len(concepts)} concepts generated")
    return concepts


def stage_catalog() -> list:
    """Run Phase 2: Pillow validation + catalog approval."""
    log.info("▶ STAGE 2: CATALOG")
    import catalog
    approved = catalog.run()
    log.info(f"✓ STAGE 2 COMPLETE — {len(approved)} concepts approved")
    return approved


def stage_upload() -> list:
    """Run Phase 3: Printful file upload + product creation + mockup generation."""
    log.info("▶ STAGE 3: UPLOAD")
    import upload
    deployed = upload.run()
    log.info(f"✓ STAGE 3 COMPLETE — {len(deployed)} products deployed to Printful")
    return deployed


def stage_deploy(generated_count: int = 0, approved_count: int = 0):
    """Run Phase 4: Storefront sync + deployment report."""
    log.info("▶ STAGE 4: DEPLOY")
    import deploy
    report = deploy.run(
        generated_count=generated_count,
        approved_count=approved_count,
    )
    log.info(f"✓ STAGE 4 COMPLETE — Storefront synced")
    return report


# ─────────────────────────────────────────────
# Main Orchestrator
# ─────────────────────────────────────────────
def run_full_pipeline(count: int = 5) -> dict:
    """
    Run the complete automation pipeline end-to-end.
    Returns a summary dict with counts and status for each stage.
    """
    start_time = datetime.utcnow()
    summary = {
        "run_at": start_time.isoformat(),
        "stages": {},
        "success": False,
        "error": None,
    }

    try:
        # Stage 1: Generate
        concepts = stage_generate(count)
        summary["stages"]["generate"] = {
            "status": "success",
            "count": len(concepts),
        }
        if not concepts:
            raise RuntimeError("No concepts generated. Check OPENAI_API_KEY and GEMINI_API_KEY.")

        # Stage 2: Catalog
        approved = stage_catalog()
        summary["stages"]["catalog"] = {
            "status": "success",
            "count": len(approved),
        }
        if not approved:
            raise RuntimeError("No concepts approved. Check image validation logs.")

        # Stage 3: Upload
        deployed = stage_upload()
        summary["stages"]["upload"] = {
            "status": "success",
            "count": len(deployed),
        }
        if not deployed:
            raise RuntimeError("No products deployed. Check PRINTFUL_API_KEY and store config.")

        # Stage 4: Deploy
        report = stage_deploy(
            generated_count=len(concepts),
            approved_count=len(approved),
        )
        summary["stages"]["deploy"] = {
            "status": "success",
            "hero": report.hero_product if report else "None",
        }

        summary["success"] = True

    except Exception as e:
        log.error(f"Pipeline failed: {e}")
        log.error(traceback.format_exc())
        summary["error"] = str(e)
        summary["success"] = False

    end_time = datetime.utcnow()
    duration = (end_time - start_time).total_seconds()
    summary["duration_seconds"] = round(duration, 1)

    # Save pipeline summary
    summary_path = Path("output/pipeline_summary.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2))

    return summary


# ─────────────────────────────────────────────
# CLI Entry Point
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Florida Man Drops — Apparel Automation Factory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 main.py                    Run full pipeline (5 concepts)
  python3 main.py --count 3          Run full pipeline (3 concepts)
  python3 main.py --stage generate   Run only generation phase
  python3 main.py --stage catalog    Run only catalog validation
  python3 main.py --stage upload     Run only Printful upload
  python3 main.py --stage deploy     Run only storefront sync
  python3 main.py --dry-run          Check environment and dependencies only
        """,
    )
    parser.add_argument(
        "--stage",
        choices=["generate", "catalog", "upload", "deploy"],
        default=None,
        help="Run only a specific pipeline stage",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=int(os.getenv("MAX_CONCEPTS", "5")),
        help="Number of concepts to generate (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate environment and dependencies only — do not run pipeline",
    )
    parser.add_argument(
        "--image-provider",
        choices=["forge", "openai"],
        default=os.getenv("IMAGE_PROVIDER", "forge"),
        help="Image generation backend: 'forge' (Manus Forge API, default) or 'openai' (DALL-E 3 via OpenAI key)",
    )
    args = parser.parse_args()
    # Propagate image provider to generate module via env var so it picks up the right config
    os.environ["IMAGE_PROVIDER"] = args.image_provider

    # Always check environment first
    log.info("=" * 60)
    log.info("FLORIDA MAN DROPS — AUTOMATION FACTORY")
    log.info(f"Started: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    log.info("=" * 60)

    if not check_environment(args.image_provider):
        sys.exit(1)

    if not check_dependencies():
        sys.exit(1)

    if args.dry_run:
        log.info("Dry run complete — environment and dependencies OK")
        log.info("Run without --dry-run to start the pipeline")
        sys.exit(0)

    # Run specific stage or full pipeline
    if args.stage:
        log.info(f"Running single stage: {args.stage}")
        if args.stage == "generate":
            result = stage_generate(args.count)
            print(f"\nGenerated {len(result)} concepts")
        elif args.stage == "catalog":
            result = stage_catalog()
            print(f"\nApproved {len(result)} concepts")
        elif args.stage == "upload":
            result = stage_upload()
            print(f"\nDeployed {len(result)} products")
        elif args.stage == "deploy":
            result = stage_deploy()
            print(f"\nDeploy complete: {result.hero_product if result else 'failed'}")
    else:
        log.info(f"Running full pipeline ({args.count} concepts)...")
        summary = run_full_pipeline(count=args.count)

        print("\n" + "=" * 60)
        print("PIPELINE SUMMARY")
        print("=" * 60)
        for stage, data in summary.get("stages", {}).items():
            status_icon = "✓" if data.get("status") == "success" else "✗"
            count_str = f" ({data.get('count', data.get('hero', ''))})" if "count" in data or "hero" in data else ""
            print(f"  {status_icon} {stage.upper()}{count_str}")

        print(f"\nStatus: {'SUCCESS' if summary['success'] else 'FAILED'}")
        print(f"Duration: {summary.get('duration_seconds', 0)}s")
        if summary.get("error"):
            print(f"Error: {summary['error']}")

        sys.exit(0 if summary["success"] else 1)


if __name__ == "__main__":
    # Ensure output directory exists before logging starts
    Path("output").mkdir(exist_ok=True)
    main()
