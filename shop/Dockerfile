FROM python:3.12-slim
WORKDIR /srv
COPY shop/requirements.txt shop/requirements.txt
RUN pip install --no-cache-dir -r shop/requirements.txt
COPY shop shop
CMD ["uvicorn", "shop.app:app", "--host", "0.0.0.0", "--port", "8001"]
