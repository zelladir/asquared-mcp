FROM python:3.12-slim

WORKDIR /app

# System deps for httpx (no special needs) — slim image is sufficient.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy only metadata first to leverage layer caching for deps.
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# Runtime data dir; mounted at compose level for persistence.
RUN mkdir -p /app/data

EXPOSE 8765

# Bind 0.0.0.0 inside the container; docker-compose maps the host port to 127.0.0.1
# so the host-side socket is not internet-reachable. cloudflared connects via loopback.
CMD ["python", "-m", "asquared_mcp.server"]
