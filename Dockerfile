# LegalEase container image.
# One image serves both processes: the default command runs the FastAPI
# backend; docker-compose overrides it to run the Streamlit frontend.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Liberation Serif (Times-metric compatible) is embedded in exported PDFs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Runtime dependencies only; requirements-dev.txt is for the test suite.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
COPY assets/ assets/
COPY .streamlit/ .streamlit/

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin legalease
USER legalease

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
