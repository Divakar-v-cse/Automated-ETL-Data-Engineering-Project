# Two-stage image: compile the React SPA, then serve it from the FastAPI process
# so the API and the UI share one origin (no CORS, one port).
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=web /web/dist ./frontend/dist

# The warehouse lives on a mounted volume so data survives container rebuilds.
VOLUME ["/app/data"]
EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/health', timeout=4).read()"

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8010"]
