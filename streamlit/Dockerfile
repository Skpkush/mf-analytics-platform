# ============================================================
# Streamlit NAV Forecasting app — container image
# Build context MUST be the repo root (needs scripts/ + streamlit/):
#   docker build -f streamlit/Dockerfile -t mf-nav-app .
# ============================================================
FROM python:3.11-slim

# build-essential kept for any source builds during pip install
# (psycopg2-binary + prophet ship wheels, so this is belt-and-braces).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install slim app-only deps first for layer caching.
COPY streamlit/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code (incl. utils/, pages/, .streamlit/) + the forecasting module it imports.
COPY scripts/ ./scripts/
COPY streamlit/ ./streamlit/

EXPOSE 8501

# Container health: Streamlit's built-in health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health',timeout=4).read().strip()==b'ok' else 1)"

CMD ["streamlit", "run", "streamlit/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
