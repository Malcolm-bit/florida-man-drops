#!/data/data/com.termux/files/usr/bin/bash

# ----------- CONFIGURABLE -----------
GITHUB_REPO="https://github.com/YOUR-USERNAME/YOUR-REPO.git"   # EDIT!
PRODUCT_ID="prod_abc123"                                       # EDIT!
SITE_URL="https://www.floridamanadventures.com"                # EDIT!
LOCAL_WEBHOOK_URL="http://localhost:300/api/webhook"          # EDIT!
FILES_TO_EDIT="components/BuyNowButton.jsx pages/api/checkout.js pages/api/webhook.js"
# -------------------------------------

error_exit() {
  echo "[!] $1"
  exit 1
}

# Function for checking the last command succeeded
check_last() {
  if [ $? -ne  ]; then
    error_exit "$1"
  fi
}

pkg install -y git nano curl nodejs || error_exit "Could not install required packages."
npm install -g stripe || error_exit "Could not install Stripe CLI."

# Clone repo if not present
REPO_DIR=$(basename "$GITHUB_REPO" .git)
if [ ! -d "$REPO_DIR" ]; then
  git clone "$GITHUB_REPO" || error_exit "Failed to clone repo."
fi
cd "$REPO_DIR" || error_exit "Failed to enter project directory."

# Ensure file presence and edit
for FILE in $FILES_TO_EDIT
do
  DIR=$(dirname "$FILE")
  if [ ! -d "$DIR" ]; then
    mkdir -p "$DIR" || error_exit "Cannot make directory $DIR"
  fi
  if [ ! -f "$FILE" ]; then
    touch "$FILE"
    echo "// New file. Paste code changes here." > "$FILE"
    echo "[!] $FILE was missing and created as a new file -- MAKE SURE TO COPY THE PATCH FROM ASSISTANT/WEB."
  fi
  echo "OPENING $FILE for editing..."
  nano "$FILE"
done

# Edit/check .env
if [ ! -f .env ]; then
  touch .env
  echo -e "# Add your Stripe keys and SITE_URL below\nSTRIPE_SECRET_KEY=\nSTRIPE_WEBHOOK_SECRET=\nSTRIPE_PUBLISHABLE_KEY=\nNEXT_PUBLIC_SITE_URL=$SITE_URL" > .env
  echo "[!] .env was missing and created. Edit it!"
fi

# Validate .env entries
for ENVVAR in STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET STRIPE_PUBLISHABLE_KEY NEXT_PUBLIC_SITE_URL
do
  grep -q "$ENVVAR=" .env || echo "[!] $ENVVAR missing in .env!"
done
nano .env

# Git add, commit, and push
git add .
echo "Enter a commit message:"; read MSG
git commit -m "$MSG" || echo "[!] Git commit failed."
git push || echo "[!] Git push failed (check your remote and credentials)!"

# Test Checkout API
echo "--- Testing Stripe Checkout endpoint (should see a URL in response) ---"
CHECKOUT_OUT=$(curl -s -w "\nHTTP_STATUS:%{http_code}\n" -X POST "$SITE_URL/api/checkout" \
  -H "Content-Type: application/json" \
  -d "{\"productId\":\"$PRODUCT_ID\",\"quantity\":1}")
BODY=$(echo "$CHECKOUT_OUT" | sed -n '/HTTP_STATUS/!p')
STATUS=$(echo "$CHECKOUT_OUT" | grep HTTP_STATUS | cut -d: -f2)
echo "Server response:"
echo "$BODY"
if [ "$STATUS" != "200" ]; then
  echo "[!] ERROR: Got HTTP $STATUS from /api/checkout -- check backend logs and code!"
else
  echo "API seems OK (HTTP 200)."
fi

# Stripe CLI webhook test
echo ""
echo "[*] Forwarding Stripe webhooks to your local endpoint for 5 seconds..."
stripe listen --forward-to "$LOCAL_WEBHOOK_URL" &
LISTEN_PID=$!
sleep 2
stripe trigger checkout.session.completed
sleep 3
kill $LISTEN_PID

echo ""
echo "If your webhook works, you will see a JSON response and (in logs/DB) the webhook event handled. Check your logs and DB for any failures!"

echo ""
echo "All steps complete. Read any errors marked with [!] above and fix as needed. For further errors, check your backend logs."
