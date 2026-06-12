#!/bin/bash
# HVOS Docker Entrypoint

set -e

echo "[HVOS] Starting Reality Layer..."
echo "[HVOS] Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# 等待依赖服务
echo "[HVOS] Waiting for PostgreSQL..."
until pg_isready -h "${POSTGRES_HOST:-postgres}" -U "${POSTGRES_USER:-hvos}" > /dev/null 2>&1; do
    sleep 2
done
echo "[HVOS] PostgreSQL ready"

echo "[HVOS] Waiting for Redis..."
until redis-cli -h "${REDIS_HOST:-redis}" ping > /dev/null 2>&1; do
    sleep 2
done
echo "[HVOS] Redis ready"

# 初始化数据库（如需要）
echo "[HVOS] Running Reality Layer collect cycle..."
python -m reality.reality_hub --config "${REALITY_CONFIG:-/app/reality_config.json}" --action collect

echo "[HVOS] Reality Layer cycle complete at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
exec "$@"