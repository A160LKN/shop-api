#!/bin/sh
# Запуск на бесплатном Render: один контейнер, поэтому учебный платёжный шлюз
# работает рядом с API на внутреннем порту, а наружу открыт только API на $PORT.
set -e
alembic upgrade head
python -m app.seed
uvicorn tools.fake_gateway:app --host 127.0.0.1 --port 8001 --log-level warning &
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
