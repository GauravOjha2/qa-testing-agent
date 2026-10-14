# SiteSentinel — Website Vulnerability & QA Scanner
# Playwright (Chromium) + axe-core + Lighthouse CLI + Gemini (gemini-flash-latest)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# --- system libs for headless Chromium + Node for Lighthouse ---------------
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates gnupg \
      libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libdbus-1-3 \
      libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
      libcairo2 libxshmfence1 libxfixes3 libgtk-3-0 libx11-xcb1 libxcb1 libegl1 \
      fonts-liberation fonts-noto-color-emoji \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Lighthouse CLI — the Core Web Vitals engine. Pinned, installed globally.
RUN npm install -g lighthouse@12 --no-fund --no-audit

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Browser + axe-core before copying the app so layers cache well.
RUN playwright install --with-deps chromium
COPY package.json package-lock.json* ./
RUN npm install --omit=dev --no-fund --no-audit || true

COPY . .

# Warm the axe-core path check and fail the build early if it is missing.
RUN python -c "from pathlib import Path; import sys; sys.exit(0 if Path('node_modules/axe-core/axe.min.js').is_file() else 'axe-core bundle missing')"

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fsS http://localhost:8080/api/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-keep-alive", "75"]
