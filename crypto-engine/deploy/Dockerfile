# Market Intelligence Engine - PAPER TRADING ONLY.
# Stage 1: build the React/TypeScript dashboard.
FROM node:22-alpine AS dashboard
WORKDIR /dash
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/ ./
RUN npm run build

# Stage 2: Python runtime.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
RUN pip install --upgrade pip && pip install .
COPY --from=dashboard /dash/dist /app/dashboard
RUN useradd --create-home --uid 10001 mie && mkdir -p /app/recordings /app/data && chown -R mie /app/recordings /app/data
USER mie
ENV MIE_API__HOST=0.0.0.0 MIE_API__PORT=8080 MIE_API__DASHBOARD_DIR=/app/dashboard
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=45s --retries=3 \
  CMD python -c "import json,sys,urllib.request; h=json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=2)); sys.exit(0 if h['status'] in ('OK','DEGRADED','STARTING') else 1)"
ENTRYPOINT ["marketintel"]
CMD ["run"]
