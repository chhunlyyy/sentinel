# Sentinel dashboard image (Phase I). It serves only the dashboard and the local API for a mounted workspace.
# The AI-tool-facing CLI is installed on the host (`uv tool install sentinel-pipeline`); this image has no AI tool CLI,
# no Node and no secret. Run it with:
#   docker run --rm -it --init -p 127.0.0.1:8765:8765 -v "$PWD":/work -v sentinel-config:/home/sentinel/.config/sentinel ghcr.io/chhunlyyy/sentinel
# The command includes --init (a small init process, so signals reach the server). Always publish on 127.0.0.1 only; add --user $(id -u):$(id -g) so files written in /work belong to you.
# There is no EXPOSE on purpose: `docker run -P` would publish on every interface. There is no HEALTHCHECK: every API route needs
# the session token, and a check must not hold one.

# ---- stage 1: build the dashboard (writes sentinel/dashboard_dist)
FROM node:22.18.0-slim AS dashboard
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 CI=1
WORKDIR /src/dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

# ---- stage 2: build the release wheel (SENTINEL_RELEASE=1 refuses a missing or stale dashboard build)
FROM python:3.12-slim AS wheel
RUN pip install --no-cache-dir "hatchling>=1.25"
WORKDIR /build
COPY pyproject.toml hatch_build.py README.md LICENSE ./
COPY sentinel/ ./sentinel/
COPY skills/ ./skills/
COPY dashboard/ ./dashboard/
COPY --from=dashboard /src/sentinel/dashboard_dist ./sentinel/dashboard_dist
RUN SENTINEL_RELEASE=1 hatchling build -t wheel -d /dist

# ---- stage 3: the runtime image
FROM python:3.12-slim
LABEL org.opencontainers.image.title="sentinel" \
      org.opencontainers.image.description="Sentinel local dashboard and API (dashboard only; the CLI is installed on the host)" \
      org.opencontainers.image.version="2.1.0" \
      org.opencontainers.image.source="https://github.com/chhunlyyy/sentinel" \
      org.opencontainers.image.licenses="MIT"
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && git config --system --add safe.directory /work
# /home/sentinel and .config are 0755 so `--user N` (any uid) can traverse to a mounted config folder; only .config/sentinel is 0700
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin sentinel \
 && install -d -o sentinel -g sentinel -m 0755 /home/sentinel /home/sentinel/.config \
 && install -d -o sentinel -g sentinel -m 0700 /home/sentinel/.config/sentinel \
 && install -d -o sentinel -g sentinel -m 0755 /work
COPY --from=wheel /dist/*.whl /tmp/wheel/
RUN pip install --no-cache-dir --no-compile "pyyaml==6.0.3" "jsonschema==4.19.2" /tmp/wheel/*.whl && rm -rf /tmp/wheel
ENV USER=sentinel LOGNAME=sentinel HOME=/home/sentinel SENTINEL_CONTAINER=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER sentinel
WORKDIR /work
ENTRYPOINT ["sentinel"]
CMD ["dashboard", "--no-open", "--bind", "0.0.0.0", "--port", "8765", "--public-host", "localhost:8765"]
