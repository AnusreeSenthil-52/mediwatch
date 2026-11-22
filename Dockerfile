FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY . .
RUN touch /app/sim.db

ENV HOST=0.0.0.0
ENV PORT=8000
EXPOSE 8000
CMD ["python", "server.py"]
