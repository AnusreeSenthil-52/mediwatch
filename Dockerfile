FROM python:3.11-slim

# Install Mosquitto MQTT broker
RUN apt-get update && apt-get install -y --no-install-recommends mosquitto && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY . .
RUN touch /app/sim.db

# Ensure mosquitto config and run directory exist
RUN mkdir -p /var/run/mosquitto && chown -R mosquitto:mosquitto /var/run/mosquitto

ENV HOST=0.0.0.0
ENV PORT=8000
EXPOSE 8000

# Start Mosquitto broker in background and run server.py
CMD ["sh", "-c", "mosquitto -d && python server.py"]

