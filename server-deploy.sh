#!/bin/bash
# Run DIRECTLY ON THE VPS (no git push step).
# Usage:  ./server-deploy.sh

set -euo pipefail

VPS_PATH="/var/www/ssalavation-tattoo"
BRANCH="main"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

step() { echo -e "\n${BOLD}${YELLOW}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }

cd "$VPS_PATH"

step "git pull"
git pull origin "$BRANCH"
ok "Code updated"

REBUILD=false
if git diff HEAD@{1} HEAD --name-only 2>/dev/null | grep -qE '^(Dockerfile|requirements\.txt|docker-compose\.yml)$'; then
    REBUILD=true
fi

step "Docker"
if [[ "$REBUILD" == true ]]; then
    echo "  Rebuilding image (Dockerfile or requirements changed)..."
    docker compose down
    docker compose up -d --build
    ok "Rebuilt and started"
else
    echo "  Restarting containers (no image change needed)..."
    docker compose down
    docker compose up -d
    ok "Restarted"
fi

step "Migrations"
docker compose exec -T backend python manage.py migrate --noinput
ok "Migrations applied"

step "Static files"
docker compose exec -T backend python manage.py collectstatic --noinput --clear 2>/dev/null || true

echo ""
echo -e "${BOLD}${GREEN}Done!${NC}"
docker compose ps
