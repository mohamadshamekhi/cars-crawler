FROM python:3.12-slim-trixie

# آینه‌ی pip (مثلاً آینه‌ی داخلی ایران)
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CHROMIUM_EXECUTABLE=/usr/bin/chromium \
    PORT=8000

WORKDIR /app

# آینه‌ی apt (دسترسی به deb.debian.org از سرور ایران ناپایدار است/تایم‌اوت می‌کند)
ARG APT_MIRROR=http://mirror.arvancloud.ir/debian

# Chromium از apt دبیان (CDN پلی‌رایت از ایران 403 می‌دهد)؛ فونت فارسی برای رندر درست متن
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|http://deb.debian.org/debian|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
        sed -i "s|http://deb.debian.org/debian|$APT_MIRROR|g" /etc/apt/sources.list 2>/dev/null; \
    fi \
    && apt-get update -o Acquire::Retries=5 -o Acquire::http::Timeout=20 \
    && apt-get install -y --no-install-recommends chromium fonts-vazirmatn fonts-liberation ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --index-url "$PIP_INDEX_URL" ${PIP_TRUSTED_HOST:+--trusted-host "$PIP_TRUSTED_HOST"} -r requirements.txt \
    && rm -rf /tmp/*

RUN useradd --create-home --uid 10001 crawler \
    && chown -R crawler:crawler /app

COPY --chown=crawler:crawler *.py ./
COPY --chown=crawler:crawler certs ./certs

USER crawler

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/docs' % os.environ.get('PORT','8000'), timeout=4)" || exit 1

CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
