"""Small helpers shared by every process."""
import json
import os

import paho.mqtt.client as mqtt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")


def load_json(name_or_path):
    path = name_or_path if os.path.isabs(name_or_path) else os.path.join(CONFIG_DIR, name_or_path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # Let container deployments point every simulator process at the broker
    # service, while keeping the checked-in local config defaults intact.
    if isinstance(data, dict) and isinstance(data.get("mqtt"), dict):
        if os.environ.get("MEDIWATCH_MQTT_HOST"):
            data["mqtt"]["host"] = os.environ["MEDIWATCH_MQTT_HOST"]
        if os.environ.get("MEDIWATCH_MQTT_PORT"):
            data["mqtt"]["port"] = int(os.environ["MEDIWATCH_MQTT_PORT"])
    return data


def make_mqtt_client(name, host="localhost", port=1883):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=name)
    client.connect(host, port, keepalive=30)
    return client


def publish(client, topic, payload):
    client.publish(topic, json.dumps(payload), qos=0)
