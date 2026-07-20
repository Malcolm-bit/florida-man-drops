#!/usr/bin/env bash

# Stripe Webhook Helper - florida-man-drops
# Author: Malcolm-bit
# Domain: floridamanadventures
# 
# This script sets up local Stripe webhook testing by forwarding
# live webhooks to your local development endpoint.

set -e

# ==================== CONFIGURE ====================
USERNAME="Malcolm-bit"
DOMAIN="floridamanadventures"
HOOK_URL="http://localhost:3000/api/webhook"
STRIPE_EVENT="checkout.session.completed"
# ===================================================

echo "╔════════════════════════════════════════════════════════╗"
echo "║     Stripe Webhook Helper - florida-man-drops          ║"
echo "║     Username: $USERNAME                               ║"
echo "║     Domain: $DOMAIN                                   ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# Step 1: Start Stripe CLI listener
echo "[1/3] Initializing Stripe CLI listener..."
echo "      Forwarding live Stripe webhooks to: $HOOK_URL"
stripe listen --forward-to "$HOOK_URL" &
LISTEN_PID=$!
echo "      Stripe CLI listener started (PID: $LISTEN_PID)"
echo ""

# Give Stripe CLI a moment to initialize
sleep 2

# Step 2: Trigger test webhook event
echo "[2/3] Triggering '$STRIPE_EVENT' test event..."
stripe trigger "$STRIPE_EVENT"
echo "      Test event triggered!"
echo ""

# Step 3: Monitor webhook
echo "[3/3] Monitoring webhook delivery..."
echo "      ✓ You should now see the webhook event reaching your handler at:"
echo "        $HOOK_URL"
echo ""
echo "════════════════════════════════════════════════════════"
echo "Press Enter to stop Stripe CLI forwarding..."
echo "════════════════════════════════════════════════════════"
read -r

# Cleanup
echo ""
echo "Stopping Stripe CLI listener..."
kill $LISTEN_PID 2>/dev/null || true
echo "Done! Webhook testing session ended."
