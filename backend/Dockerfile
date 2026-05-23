FROM python:3.11-slim AS base

WORKDIR /app
COPY backend/pyproject.toml backend/README.md ./
RUN pip install --no-cache-dir -e .
COPY backend/app ./app
COPY backend/packages ./packages

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

