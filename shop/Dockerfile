FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_DEFAULT_TIMEOUT=100 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY shop/requirements.txt shop/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install -r shop/requirements.txt
COPY shop shop
EXPOSE 8001
CMD ["uvicorn", "shop.app:app", "--host", "0.0.0.0", "--port", "8001"]
