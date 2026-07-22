#!/bin/bash
# Run from your LOCAL machine.
# Usage:
#   ./deploy.sh                        → commits with default message and deploys
#   ./deploy.sh "feat: add new thing"  → commits with custom message and deploys
#   ./deploy.sh --vps-only             → skip git push, just SSH-deploy what's on VPS

set -euo pipefail

# ── CONFIG ─────────────────────────────────────────────────────────────────────
# Reads VPS_HOST (and optionally VPS_USER) from a local .deploy file.
# .deploy is gitignored — your IP never goes to GitHub.
# Create it once:  echo 'VPS_HOST=your.vps.ip' > .deploy
VPS_USER="root"
VPS_HOST=""
VPS_PATH="/var/www/ssalavation-tattoo"
BRANCH="main"

DEPLOY_CONFIG="$(dirname "$0")/.deploy"
if [[ -f "$DEPLOY_CONFIG" ]]; then
    # shellcheck source=/dev/null
    source "$DEPLOY_CONFIG"
fi

if [[ -z "$VPS_HOST" ]]; then
    err "VPS_HOST is not set. Create a .deploy file:\n  echo 'VPS_HOST=your.vps.ip' > .deploy"
fi
# ───────────────────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

step() { echo -e "\n${BOLD}${YELLOW}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }
err()  { echo -e "${RED}✗ $1${NC}"; exit 1; }

VPS_ONLY=false
COMMIT_MSG="${1:-}"

if [[ "$COMMIT_MSG" == "--vps-only" ]]; then
    VPS_ONLY=true
    COMMIT_MSG=""
fi

# ── STEP 1: PUSH CODE ──────────────────────────────────────────────────────────
if [[ "$VPS_ONLY" == false ]]; then
    step "Pushing code to GitHub"

    if [[ -z "$COMMIT_MSG" ]]; then
        COMMIT_MSG="chore: deploy $(date '+%Y-%m-%d %H:%M')"
    fi

    # Stage all tracked + new files (excluding .gitignored ones)
    git add -A

    # Only commit if there's something staged
    if git diff --cached --quiet; then
        echo "  Nothing to commit — working tree clean."
    else
        git commit -m "$COMMIT_MSG"
        ok "Committed: $COMMIT_MSG"
    fi

    git push origin "$BRANCH"
    ok "Pushed to origin/$BRANCH"
fi

# ── STEP 2: DEPLOY ON VPS ──────────────────────────────────────────────────────
step "Deploying on VPS ($VPS_USER@$VPS_HOST)"

ssh -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" bash << REMOTE
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

step() { echo -e "\n\${BOLD}\${YELLOW}  [\$1]\${NC}"; }
ok()   { echo -e "  \${GREEN}✓ \$1\${NC}"; }

cd "$VPS_PATH"

step "git pull"
git pull origin "$BRANCH"
ok "Code updated"

# The Dockerfile bakes the source in with 'COPY . /app/' and there is no code
# volume, so a restart would keep serving the OLD image. Always rebuild.
# --force-recreate also makes the container re-read .env.production, which a
# plain restart never does.
DEEP_REBUILD=false
if git diff HEAD@{1} HEAD --name-only 2>/dev/null | grep -qE '^(Dockerfile|requirements\.txt|docker-compose\.yml)$'; then
    DEEP_REBUILD=true
fi

step "Docker"
if [[ "\$DEEP_REBUILD" == true ]]; then
    echo "  Dockerfile/requirements/compose changed — full rebuild from scratch..."
    docker compose down --remove-orphans
    docker system prune -f
    docker compose up -d --build
else
    echo "  Rebuilding backend image (layer cache makes this fast)..."
    # Build the new image, then reconcile ALL services together. Recreating only
    # the backend can lose the depends_on healthcheck race against the db mid-
    # restart ("dependency db failed to start"); a full 'up -d' brings db + backend
    # up in order. The db keeps its data volume, so it is only recreated if needed.
    docker compose build backend
    docker compose up -d
fi

echo "  Waiting for backend to be ready..."
until docker compose exec -T backend echo "ready" >/dev/null 2>&1; do sleep 1; done
ok "Backend rebuilt and started"

step "Migrations"
docker compose exec -T backend python manage.py migrate --noinput
ok "Migrations applied"

step "Static files"
docker compose exec -T backend python manage.py collectstatic --noinput --clear 2>/dev/null || true

# Fail loudly rather than reporting success over a crash-looping container.
step "Health check"
docker compose exec -T backend python manage.py check --deploy --fail-level ERROR >/dev/null
ok "Django check passed"

echo ""
echo -e "\${BOLD}\${GREEN}Deployment complete!\${NC}"
docker compose ps
REMOTE

ok "All done — https://api.salvationhq.com"
