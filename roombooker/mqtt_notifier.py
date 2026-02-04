import os
from typing import Optional

import paho.mqtt.client as mqtt


class MqttNotifier:
    def __init__(self, logger) -> None:
        self.logger = logger
        self.host = os.environ.get("MQTT_HOST", "")
        self.username = os.environ.get("MQTT_USERNAME", "")
        self.password = os.environ.get("MQTT_PASSWORD", "")
        self.port = int(os.environ.get("MQTT_PORT", "1883"))
        self.topic = os.environ.get("MQTT_TOPIC", "roombooker/status")

    def send_status(self, status: str, message: Optional[str] = None) -> None:
        if not self.host:
            self.logger.log("MQTT_HOST nicht gesetzt. Überspringe MQTT Nachricht.")
            return

        payload = status if message is None else f"{status}: {message}"
        client = mqtt.Client()
        if self.username:
            client.username_pw_set(self.username, self.password)

        try:
            client.connect(self.host, self.port, 60)
            client.publish(self.topic, payload)
            client.disconnect()
            self.logger.log(f"MQTT gesendet: {payload}")
        except Exception as exc:
            self.logger.log(f"MQTT Fehler: {exc}")
