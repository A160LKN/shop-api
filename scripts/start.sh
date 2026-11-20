#!/bin/sh
# Единственный сценарий запуска API — в Docker Compose, в CI и на Render:
# миграции, демо-данные, сервер. Раньше Dockerfile и Render запускались по-разному, и поведение расходилось.
#
# FAKE_GATEWAY=true — запустить учебный платёжный шлюз в этом же контейнере, на внутреннем порту.
# Нужно на бесплатном Render, где контейнер один; в Docker Compose шлюз — отдельный сервис payments.
# Число процессов uvicorn берёт из WEB_CONCURRENCY, порт — из PORT (его задаёт Render).
set -e
alembic upgrade head
python -m app.seed
if [ "${FAKE_GATEWAY:-false}" = "true" ]; then
  uvicorn tools.fake_gateway:app --host 127.0.0.1 --port 8001 --log-level warning &
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
