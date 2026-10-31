# The demo shop SIMULATION as its own container, so FixOnce watches it over HTTP the same way it
# would watch a real service. The code lives in the fixonce package (backend/fixonce/demo/shop.py).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_DEFAULT_TIMEOUT=100 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
RUN --mount=type=cache,target=/root/.cache/pip pip install "fastapi>=0.110" "uvicorn>=0.29"
COPY backend/fixonce/__init__.py backend/fixonce/__init__.py
COPY backend/fixonce/demo backend/fixonce/demo
WORKDIR /srv/backend
EXPOSE 8001
CMD ["uvicorn", "fixonce.demo.shop:app", "--host", "0.0.0.0", "--port", "8001"]
