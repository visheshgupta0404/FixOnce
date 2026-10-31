# One-container image for free hosting (Render). The demo shop runs inside the backend process
# (SHOP_URL=inprocess), so only the FixOnce API and page are public. Local dev uses docker-compose.yml.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_DEFAULT_TIMEOUT=100 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
ENV SHOP_URL=inprocess
WORKDIR /srv/backend
EXPOSE 8000
CMD ["sh", "-c", "uvicorn fixonce.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
