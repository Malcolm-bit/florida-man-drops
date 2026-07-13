#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# Florida Man Drops — Termux Setup Script
# ============================================================
# Run once after cloning the repo:
#   bash setup_termux.sh
#
# Termux-specific fixes applied:
#   - Uses pip3 (NOT pip install --upgrade pip)
#   - Installs grpcio pre-built wheel BEFORE google-generativeai
#     (google-ai-generativelanguage pulls in google-api-core[grpc]
#      which requires grpcio; without a pre-built wheel it tries to
#      compile from source and fails with Permission denied)
#   - Pre-built aarch64 wheels exist for grpcio 1.x on PyPI
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
echo "[1/6] Updating Termux packages..."
pkg update -y && pkg upgrade -y

# ─────────────────────────────────────────────
# 2. Install system dependencies required by Pillow
# ─────────────────────────────────────────────
echo "[2/6] Installing libjpeg, libpng, libwebp (required by Pillow)..."
pkg install -y libjpeg-turbo libpng libwebp

# ─────────────────────────────────────────────
# 3. Install grpcio pre-built wheel FIRST
#    google-ai-generativelanguage → google-api-core[grpc] → grpcio
#    Pre-built musllinux aarch64 wheel exists on PyPI — no compilation needed.
#    Must be installed before google-generativeai or pip will try to build it.
# ─────────────────────────────────────────────
echo "[3/6] Installing grpcio pre-built wheel (required by google-generativeai)..."
pip3 install grpcio --prefer-binary

# ─────────────────────────────────────────────
# 4. Install remaining Python packages
#    NOTE: Do NOT run 'pip install --upgrade pip' in Termux —
#    it overwrites the Termux-managed pip and breaks things.
# ─────────────────────────────────────────────
echo "[4/6] Installing pipeline dependencies..."
pip3 install \
    openai \
    Pillow \
    google-generativeai \
    tenacity \
    requests

echo "  ✓ All Python packages installed"

# ─────────────────────────────────────────────
# 5. Create .env template (if not already present)
# ─────────────────────────────────────────────
echo "[5/6] Creating .env template..."
if [ -f ".env" ]; then
    echo "  .env already exists — skipping (edit it manually)"
else
    cat > .env << 'EOF'
# ============================================================
# Florida Man Drops — Environment Variables
# ============================================================
# Fill in your API keys below, then run:
#   source .env && python3 main.py --dry-run

# Required: Viral trend detection
# Get from: https://aistudio.google.com/apikey
GEMINI_API_KEY=

# Required: Printful Bearer token
# Get from: https://developers.printful.com → Private token
PRINTFUL_API_KEY=

# Required for image generation on Termux
# Get from: https://platform.openai.com/api-keys
OPENAI_API_KEY=

# Use OpenAI DALL-E 3 by default (no Forge API needed on Termux)
IMAGE_PROVIDER=openai

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
# 6. Verify environment
# ─────────────────────────────────────────────
echo "[6/6] Running environment check..."
if [ -f ".env" ]; then
    # shellcheck disable=SC1091
    set -a && source .env && set +a
fi

python3 main.py --image-provider openai --dry-run \
    && echo "" && echo "  ✓ Environment check passed" \
    || echo "  ✗ Fill in .env and re-run: source .env && python3 main.py --dry-run"

echo ""
echo "============================================================"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. Edit .env and fill in your API keys:"
echo "       nano .env"
echo "  2. Load env:"
echo "       source .env"
echo "  3. Single-concept test:"
echo "       python3 main.py --count 1 --stage generate"
echo "  4. Full pipeline:"
echo "       python3 main.py --count 3"
echo "============================================================"
echo ""
