FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_DEFAULT_TIMEOUT=100 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY web web
WORKDIR /srv/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
