# Florida Man Drops — Apparel Automation Factory

> High-velocity apparel dropshipping automation engine. Built for rapid, data-driven scaling from viral trend identification to print-ready deployment.

An autonomous, AI-driven dropshipping pipeline that turns viral cultural moments into high-quality apparel designs and deploys them to Printful for fulfillment at [floridamanadventures.shop](https://floridamanadventures.shop).

---

## Features

- **Viral Trend Monitor** — Gemini detects high-potential Florida/Angler trends and scores them by confidence
- **AI Design Engine** — Dual image provider: DALL-E 3 (OpenAI API) for Termux/external machines, or Manus Forge API in the sandbox. Generates print-ready 3600×4800px PNG assets
- **Dual Brand Styles** — Every concept is assigned a design style: `smack` (bold viral text-heavy, Smack Apparel aesthetic) or `retro` (vintage badge, distressed screen-print, burnt orange/navy palette)
- **FMA Badge Composite** — Retro FMA brand badge is automatically composited onto every approved design before Printful upload
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
  │     ├── Assigns design_style: 'smack' or 'retro'
  │     ├── Builds print-ready image prompt (style-specific)
  │     ├── Calls DALL-E 3 (OpenAI) or Forge API → saves PNG
  │     └── Retries up to 3× on generation failure (tenacity)
  │
  ├── Stage 2: catalog.py
  │     ├── Validates each PNG with Pillow (DPI, format, transparency, dimensions)
  │     ├── Upscales to 3600×4800px if needed (Lanczos + Sharpen)
  │     ├── Composites FMA retro badge (bottom-right, 320px) onto every approved design
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
pip install openai Pillow google-generativeai tenacity requests
```

### 3. Configure environment

```bash
cp .env.example .env   # or use the .env created by setup_termux.sh
# Edit .env and fill in your API keys
```

| Variable | Description | Where to get it |
|---|---|---|
| `OPENAI_API_KEY` | DALL-E 3 image generation | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `GEMINI_API_KEY` | Viral trend detection | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `PRINTFUL_API_KEY` | Printful Bearer token | [developers.printful.com](https://developers.printful.com) → Private token |

### 4. Validate environment

```bash
source .env && python3 main.py --image-provider openai --dry-run
```

### 5. Run the full pipeline

```bash
python3 main.py --image-provider openai
```

---

## Usage

```bash
python3 main.py                              # Full pipeline (5 concepts)
python3 main.py --count 3                    # Full pipeline (3 concepts)
python3 main.py --stage generate             # Generation only
python3 main.py --stage catalog              # Validation only
python3 main.py --stage upload               # Printful upload only
python3 main.py --stage deploy               # Storefront sync only
python3 main.py --dry-run                    # Check environment only
python3 main.py --image-provider openai      # Use DALL-E 3 (Termux / external)
python3 main.py --image-provider forge       # Use Manus Forge API (sandbox default)
```

### Image Provider

| Provider | Flag | When to use |
|---|---|---|
| `openai` | `--image-provider openai` | Termux, local machine, CI — requires `OPENAI_API_KEY` |
| `forge` | `--image-provider forge` (default) | Manus sandbox — requires `BUILT_IN_FORGE_API_URL` + `BUILT_IN_FORGE_API_KEY` |

You can also set `IMAGE_PROVIDER=openai` in `.env` to make it the default without passing the flag every time.

---

## Termux Setup

Run the one-shot setup script after cloning:

```bash
# 1. Clone
git clone https://github.com/Malcolm-bit/florida-man-drops.git
cd florida-man-drops

# 2. Bootstrap (installs packages, creates .env template, runs dry-run)
bash setup_termux.sh

# 3. Fill in your API keys
nano .env

# 4. Load env and run a single-concept test
source .env && python3 main.py --image-provider openai --count 1 --stage generate

# 5. Full pipeline
python3 main.py --image-provider openai --count 3
```

### Required API keys for Termux

| Variable | Description | Where to get it |
|---|---|---|
| `OPENAI_API_KEY` | DALL-E 3 image generation | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `GEMINI_API_KEY` | Viral trend detection | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `PRINTFUL_API_KEY` | Printful Bearer token | [developers.printful.com](https://developers.printful.com) → Private token |

---

## Design Styles

Every concept generated by Gemini is assigned one of two brand styles:

| Style | Aesthetic | Colors | Typography |
|---|---|---|---|
| `smack` | Bold viral text-heavy (Smack Apparel) | Black, white, neon green | Impact / Anton / Bebas Neue |
| `retro` | Vintage badge, distressed screen-print | Burnt orange, navy, cream | Rockwell / Clarendon / Cooper Black |

The FMA retro badge (`assets/fma_retro_badge_logo.png`) is composited at 320px onto the bottom-right corner of every approved design in Stage 2 (catalog.py), regardless of style.

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
| Image generation (DALL-E 3 / Forge) | 3 | 2s → 4s → 8s |
| Image upscale (Pillow) | 3 | 1s → 2s → 8s |
| Printful file upload | 4 | 3s → 6s → 30s |
| Printful product create | 3 | 5s → 10s → 60s |
| Printful mockup generate | 4 | 5s → 15s → 60s |
| Webhook notification | 3 | 2s → 4s → 15s |
