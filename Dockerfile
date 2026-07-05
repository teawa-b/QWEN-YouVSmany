FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/README.md ./backend/
COPY backend/src ./backend/src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ./backend

COPY frontend ./frontend
COPY backend/data ./backend/data
