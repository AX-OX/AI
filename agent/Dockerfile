FROM python:3.11-slim
WORKDIR /app
COPY agent/requirements.lock.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY agent/app ./app
COPY agent/prompts ./prompts
COPY agent/fixtures ./fixtures
COPY AX_Navigator_AI_MVP_v3 ./AX_Navigator_AI_MVP_v3
ENV DATASET_DIR=/app/AX_Navigator_AI_MVP_v3
ENV AX_POLICY_FILE=/app/AX_Navigator_AI_MVP_v3/config/ax_score_policy_v1.json
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
