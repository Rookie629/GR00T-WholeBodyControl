from __future__ import annotations

from typing import Any

from gear_sonic_deploy.sonic_data.sensor_transport import ImageMessageSchema, SensorClient


class ComposedCameraClientSensor(SensorClient):
    """Minimal client for the bridged typed-image stream."""

    def __init__(self, server_ip: str, port: int):
        self.start_client(server_ip, port)

    def read(self) -> dict[str, Any]:
        payload = self.receive_message()
        return ImageMessageSchema.deserialize(payload).asdict()

    def close(self) -> None:
        self.stop_client()
