FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_DEFAULT_TIMEOUT=100 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
# the cache mount keeps downloaded wheels, so a build that times out resumes instead of starting over
RUN --mount=type=cache,target=/root/.cache/pip pip install -r backend/requirements.txt
COPY backend backend
WORKDIR /srv/backend
EXPOSE 8000
CMD ["uvicorn", "fixonce.main:app", "--host", "0.0.0.0", "--port", "8000"]
