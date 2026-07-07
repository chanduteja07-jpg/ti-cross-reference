# Works on any Docker host (Hugging Face Spaces, Fly.io, Cloud Run, Railway…).
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "gunicorn app:app --workers 1 --threads 8 --timeout 180 --preload --bind 0.0.0.0:${PORT}"]
