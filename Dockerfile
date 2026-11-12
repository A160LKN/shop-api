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

# Приложение не работает от root
RUN useradd --create-home shop
USER shop

EXPOSE 8000
# При старте: применить миграции, загрузить демо-данные, запустить сервер
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
