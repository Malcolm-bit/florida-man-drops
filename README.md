# Florida Man Drops — Apparel Automation Factory

> High-velocity apparel dropshipping automation engine. Built for rapid, data-driven scaling from viral trend identification to print-ready deployment.

An autonomous, AI-driven dropshipping pipeline that turns viral cultural moments into high-quality apparel designs and deploys them to Printful for fulfillment at [floridamanadventures.com](https://www.floridamanadventures.com).

---

## Features

- **Viral Trend Monitor** — Gemini detects high-potential Florida/Angler trends and scores them by confidence
- **AI Design Engine** — DALL-E 3 generates print-ready 3600×4800px PNG assets with transparent backgrounds
- **Pillow Validation** — Automatic DPI, format, and dimension checks before any image touches Printful
- **Resilient Factory** — Printful API integration with Bearer token auth and automated error handling
- **Self-Healing** — tenacity retry logic with exponential backoff on every API call
- **Storefront Sync** — Deploys live product data to the React storefront automatically

---

## Pipeline Architecture

```
main.py
  │
  ├── Stage 1: generate.py
  │     ├── Gemini detects viral Florida/Angler trends
  │     ├── Scores concepts by confidence (0–100)
  │     ├── Builds print-ready DALL-E 3 prompt
  │     ├── Calls DALL-E 3 API → saves PNG (3600×4800px)
  │     └── Retries up to 3× on generation failure (tenacity)
  │
  ├── Stage 2: catalog.py
  │     ├── Validates each PNG with Pillow (DPI, format, transparency, dimensions)
  │     ├── Upscales to 3600×4800px if needed (Lanczos + Sharpen)
  │     ├── Filters by confidence score (default: ≥75)
  │     └── Saves approved_catalog.json + rejected_catalog.json
  │
  ├── Stage 3: upload.py
  │     ├── Uploads print-ready PNG to Printful /files (Bearer auth)
  │     ├── Creates sync product with print_area placement (front center, 12×16 in)
  │     ├── Generates mockup via Printful mockup-generator API
  │     ├── Retries up to 4× per API call (tenacity + exponential backoff)
  │     └── Saves deployed_products.json
  │
  └── Stage 4: deploy.py
        ├── Selects hero product (highest confidence score)
        ├── Archives products older than 7 days
        ├── Saves storefront_products.json (consumed by React frontend)
        └── Sends optional webhook notification
```

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/Malcolm-bit/florida-man-drops.git
cd florida-man-drops
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your API keys
```

| Variable | Description | Where to get it |
|---|---|---|
| `OPENAI_API_KEY` | DALL-E 3 image generation | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `GEMINI_API_KEY` | Viral trend detection | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `PRINTFUL_API_KEY` | Printful Bearer token | [developers.printful.com](https://developers.printful.com) → Private token |

### 4. Validate environment

```bash
python3 main.py --dry-run
```

### 5. Run the full pipeline

```bash
python3 main.py
```

---

## Usage

```bash
python3 main.py                    # Full pipeline (5 concepts)
python3 main.py --count 3          # Full pipeline (3 concepts)
python3 main.py --stage generate   # Generation only
python3 main.py --stage catalog    # Validation only
python3 main.py --stage upload     # Printful upload only
python3 main.py --stage deploy     # Storefront sync only
python3 main.py --dry-run          # Check environment only
```

---

## Termux Setup

```bash
pkg install python
git clone https://github.com/Malcolm-bit/florida-man-drops.git
cd florida-man-drops
pip install -r requirements.txt
cp .env.example .env
nano .env
python3 main.py --dry-run
python3 main.py
```

---

## Print Specifications

| Spec | Value |
|---|---|
| Resolution | 3600 × 4800 px |
| DPI | 300 |
| Format | PNG-24 |
| Background | Transparent (RGBA) |
| Print placement | Front center |
| Print dimensions | 12 × 16 inches |
| Garment | Bella + Canvas 3001 (Printful product ID 71) |

---

## Retry Logic (tenacity)

| Stage | Max Retries | Backoff |
|---|---|---|
| DALL-E 3 generation | 3 | 2s → 4s → 8s |
| Image upscale (Pillow) | 3 | 1s → 2s → 8s |
| Printful file upload | 4 | 3s → 6s → 30s |
| Printful product create | 3 | 5s → 10s → 60s |
| Printful mockup generate | 4 | 5s → 15s → 60s |
| Webhook notification | 3 | 2s → 4s → 15s |
