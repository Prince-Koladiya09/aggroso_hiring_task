# Multi-stage Dockerfile for Data Privacy Request Fulfilment Workbench

# Stage 1: Build Frontend SPA
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend/ ./
RUN npm run build

# Stage 2: Python Backend & Final Container
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    APP_ENV=production

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install backend dependencies
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r ./backend/requirements.txt

# Copy policy, prompts, backend code
COPY policy/ ./policy/
COPY prompts/ ./prompts/
COPY backend/ ./backend/
COPY scripts/ ./scripts/

# Copy built frontend assets to backend static mount directory
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/api/health || exit 1

# Launch application
# SECRET_KEY: use the supplied value, otherwise generate a random one for this container run
# (sessions then end when the container restarts). Set SECRET_KEY for stable sessions.
CMD ["sh", "-c", "export SECRET_KEY=${SECRET_KEY:-$(python -c 'import secrets;print(secrets.token_hex(32))')}; exec python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]
