#!/usr/bin/env bash
# دیپلوی مستقل سرویس crawler روی سرور: ~/khodroban/crwoler/deploy.sh
set -euo pipefail

# کل منطق داخل main است تا git reset (که خود این فایل را عوض می‌کند) وسط اجرا اثری نگذارد
main() {
  local app_dir lock_file service="crawler" status i
  app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  lock_file="${HOME}/khodroban/.deploy.lock"

  cd "$app_dir"

  exec 9>"$lock_file"
  echo "[deploy] waiting for lock ${lock_file}..."
  flock 9

  echo "[deploy] updating code..."
  git fetch origin main
  git reset --hard origin/main

  if [ ! -f .env ]; then
    echo "[deploy] .env not found in ${app_dir} (copy .env.production.example)" >&2
    exit 1
  fi

  echo "[deploy] building..."
  docker compose build "$service"
  docker compose up -d "$service"

  echo "[deploy] waiting for ${service} to become healthy (max 3m)..."
  for i in $(seq 1 36); do
    status="$(docker compose ps --format '{{.Health}}' "$service" 2>/dev/null || true)"
    echo "[${i}/36] ${service} health: ${status:-unknown}"
    if [ "$status" = "healthy" ]; then
      echo "[deploy] ${service} is healthy"
      docker image prune -f
      return 0
    fi
    sleep 5
  done

  echo "[deploy] ${service} did not become healthy within 3 minutes" >&2
  docker compose ps "$service" || true
  docker compose logs --tail=100 "$service" || true
  exit 1
}

main "$@"
