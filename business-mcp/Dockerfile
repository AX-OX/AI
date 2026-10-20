FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py spring_client.py dto.py ./
CMD ["python", "server.py"]
