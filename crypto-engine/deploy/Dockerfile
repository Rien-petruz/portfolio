# Market Intelligence Engine - observation-only runtime image.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
RUN pip install --upgrade pip && pip install .

# Run as an unprivileged user; recordings go to a mounted volume.
RUN useradd --create-home --uid 10001 mie && mkdir -p /app/recordings && chown mie /app/recordings
USER mie

ENV MIE_API__HOST=0.0.0.0 \
    MIE_API__PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import json,sys,urllib.request; h=json.load(urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)); sys.exit(0 if h['status'] in ('OK','DEGRADED','STARTING') else 1)"

ENTRYPOINT ["marketintel"]
CMD ["run"]
