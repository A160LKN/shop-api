FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Сначала зависимости — этот слой кешируется и не пересобирается при каждой правке кода
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY migrations migrations
COPY tools tools
COPY alembic.ini .
COPY scripts/start.sh scripts/start-render.sh scripts/

# Приложение не работает от root
RUN useradd --create-home shop
USER shop

EXPOSE 8000
# При старте: миграции, демо-данные, сервер — тот же сценарий, что на Render (scripts/start.sh)
CMD ["sh", "scripts/start.sh"]
