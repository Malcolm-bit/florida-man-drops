#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# Florida Man Drops — Termux Setup Script
# ============================================================
# Run once after cloning the repo:
#   bash setup_termux.sh
#
# What this does:
#   1. Updates Termux packages
#   2. Installs Python 3 + pip
#   3. Installs all Python dependencies
#   4. Creates a .env template for your API keys
#   5. Verifies the environment is ready
# ============================================================

set -e

echo ""
echo "============================================================"
echo "  Florida Man Drops — Termux Setup"
echo "============================================================"
echo ""

# ─────────────────────────────────────────────
# 1. Update Termux packages
# ─────────────────────────────────────────────
echo "[1/5] Updating Termux packages..."
pkg update -y && pkg upgrade -y

# ─────────────────────────────────────────────
# 2. Install system dependencies
# ─────────────────────────────────────────────
echo "[2/5] Installing Python, libjpeg, libpng (required by Pillow)..."
pkg install -y python libjpeg-turbo libpng

# ─────────────────────────────────────────────
# 3. Install Python packages
# ─────────────────────────────────────────────
echo "[3/5] Installing Python dependencies..."
pip install --upgrade pip
pip install \
    openai \
    Pillow \
    google-generativeai \
    tenacity \
    requests

echo "  ✓ All Python packages installed"

# ─────────────────────────────────────────────
# 4. Create .env template (if not already present)
# ─────────────────────────────────────────────
echo "[4/5] Creating .env template..."
if [ -f ".env" ]; then
    echo "  .env already exists — skipping (edit it manually)"
else
    cat > .env << 'EOF'
# ============================================================
# Florida Man Drops — Environment Variables
# ============================================================
# Fill in your API keys below, then run:
#   source .env && python3 main.py --image-provider openai --dry-run

# Required: Viral trend detection
# Get from: https://aistudio.google.com/apikey
GEMINI_API_KEY=

# Required: Printful Bearer token
# Get from: https://developers.printful.com → Private token
PRINTFUL_API_KEY=

# Required for --image-provider openai (Termux default)
# Get from: https://platform.openai.com/api-keys
OPENAI_API_KEY=

# Optional: Scope to a specific Printful store ID
# PRINTFUL_STORE_ID=

# Optional: Number of concepts per run (default: 5)
# MAX_CONCEPTS=3

# Optional: Minimum confidence score to approve a concept (default: 75)
# MIN_CONFIDENCE=75

# Optional: Webhook URL to POST on successful deployment
# DEPLOY_WEBHOOK_URL=
EOF
    echo "  ✓ .env template created — fill in your API keys before running"
fi

# ─────────────────────────────────────────────
# 5. Verify environment
# ─────────────────────────────────────────────
echo "[5/5] Running environment check..."
if [ -f ".env" ]; then
    # shellcheck disable=SC1091
    set -a && source .env && set +a
fi

python3 main.py --image-provider openai --dry-run && echo "" && echo "  ✓ Environment check passed" || echo "  ✗ Fill in .env and re-run: source .env && python3 main.py --image-provider openai --dry-run"

echo ""
echo "============================================================"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. Edit .env and fill in your API keys"
echo "  2. Load env:  source .env"
echo "  3. Test run:  python3 main.py --image-provider openai --count 1 --stage generate"
echo "  4. Full run:  python3 main.py --image-provider openai --count 3"
echo "============================================================"
echo ""
