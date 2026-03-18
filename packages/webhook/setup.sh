#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_DIR="$HOME/.config/github-webhook-mcp"
ENV_FILE="$ENV_DIR/.env"
LOG_DIR="$HOME/Library/Logs/github-webhook-mcp"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

echo "=== GitHub Webhook MCP Server Setup ==="

# --- Step 1: Smee channel ---
if [[ -f "$ENV_FILE" ]] && grep -q SMEE_CHANNEL_URL "$ENV_FILE"; then
    SMEE_URL=$(grep SMEE_CHANNEL_URL "$ENV_FILE" | cut -d= -f2-)
    echo "Using existing Smee channel: $SMEE_URL"
else
    echo "Creating new Smee.io channel..."
    SMEE_URL=$(curl -sL https://smee.io/new -o /dev/null -w '%{url_effective}')
    echo "Created: $SMEE_URL"
fi

# --- Step 2: Webhook secret ---
if [[ -f "$ENV_FILE" ]] && grep -q GITHUB_WEBHOOK_SECRET "$ENV_FILE"; then
    WEBHOOK_SECRET=$(grep GITHUB_WEBHOOK_SECRET "$ENV_FILE" | cut -d= -f2-)
    echo "Using existing webhook secret"
else
    WEBHOOK_SECRET=$(openssl rand -hex 32)
    echo "Generated webhook secret"
fi

# --- Step 3: Write .env ---
mkdir -p "$ENV_DIR"
cat > "$ENV_FILE" <<EOF
SMEE_CHANNEL_URL=$SMEE_URL
GITHUB_WEBHOOK_SECRET=$WEBHOOK_SECRET
GITHUB_USERNAME=mikelane
MCP_PORT=8321
DB_PATH=$HOME/.local/share/github-webhook-mcp/events.db
EOF
chmod 600 "$ENV_FILE"
echo "Wrote $ENV_FILE"

# --- Step 4: Configure GitHub webhooks ---
echo ""
echo "Which repos should receive webhooks? (space-separated, e.g. 'owner/repo1 owner/repo2')"
echo "Leave empty to skip webhook configuration."
read -ra REPOS

for REPO in "${REPOS[@]}"; do
    echo "Configuring webhook for $REPO..."
    if gh api "repos/$REPO/hooks" \
        -f "config[url]=$SMEE_URL" \
        -f "config[content_type]=json" \
        -f "config[secret]=$WEBHOOK_SECRET" \
        -F "active=true" \
        -f "events[]=pull_request" \
        -f "events[]=pull_request_review" \
        -f "events[]=pull_request_review_comment" \
        -f "events[]=check_run" \
        -f "events[]=check_suite" \
        -f "events[]=workflow_run" \
        -f "events[]=push" \
        -f "events[]=issues" \
        --silent; then
        echo "  Done: $REPO"
    else
        echo "  Failed: $REPO (may already exist)" >&2
    fi
done

# --- Step 5: Install Python deps ---
echo ""
echo "Installing Python dependencies..."
cd "$SCRIPT_DIR"
uv sync --all-groups

# --- Step 6: Set up Caddy ---
echo ""
echo "Setting up Caddy..."
CADDY_CONFIG="/opt/homebrew/etc/Caddyfile"
if [[ -f "$CADDY_CONFIG" ]] && ! diff -q "$SCRIPT_DIR/Caddyfile" "$CADDY_CONFIG" > /dev/null 2>&1; then
    echo "WARNING: Existing Caddyfile differs. Backing up to ${CADDY_CONFIG}.bak"
    cp "$CADDY_CONFIG" "${CADDY_CONFIG}.bak"
fi
cp "$SCRIPT_DIR/Caddyfile" "$CADDY_CONFIG"
brew services start caddy 2>/dev/null || brew services restart caddy
echo "Caddy started"

# --- Step 7: Install LaunchAgents ---
echo ""
mkdir -p "$LOG_DIR"
GUI_DOMAIN="gui/$(id -u)"

# Bonjour registration
cp "$SCRIPT_DIR/launchagents/com.local.smee-bonjour.plist" "$LAUNCH_AGENTS/"
launchctl bootout "$GUI_DOMAIN/com.local.smee-bonjour" 2>/dev/null || true
launchctl bootstrap "$GUI_DOMAIN" "$LAUNCH_AGENTS/com.local.smee-bonjour.plist"
echo "Bonjour registration installed (smee.local)"

# MCP server
cp "$SCRIPT_DIR/launchagents/com.mikelane.github-webhook-mcp.plist" "$LAUNCH_AGENTS/"
launchctl bootout "$GUI_DOMAIN/com.mikelane.github-webhook-mcp" 2>/dev/null || true
launchctl bootstrap "$GUI_DOMAIN" "$LAUNCH_AGENTS/com.mikelane.github-webhook-mcp.plist"
echo "MCP server LaunchAgent installed"

# --- Step 8: Register in Claude Code settings ---
echo ""
echo "Registering MCP server in Claude Code settings..."
if command -v claude > /dev/null; then
    claude mcp remove github-webhooks 2>/dev/null || true
    claude mcp add --transport sse --scope user github-webhooks http://smee.local/sse
    echo "Registered github-webhooks via claude mcp add"
else
    echo "claude CLI not found. Run manually:"
    echo '  claude mcp add --transport sse --scope user github-webhooks http://smee.local/sse'
fi

echo ""
echo "=== Setup complete ==="
echo "Smee channel: $SMEE_URL"
echo "MCP URL:      http://smee.local/sse"
echo "Logs:         $LOG_DIR/"
echo "Config:       $ENV_FILE"
