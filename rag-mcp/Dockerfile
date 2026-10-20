FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common.py pgvector_client.py index.py server.py ./
CMD ["python", "server.py"]
