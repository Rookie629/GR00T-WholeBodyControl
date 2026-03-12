from __future__ import annotations

from collections import deque
import threading

import rclpy
from std_msgs.msg import String as RosStringMsg

from gear_sonic_deploy.sonic_data.ros_utils import ROSManager
from gear_sonic_deploy.sonic_data.topics import KEYBOARD_LISTENER_TOPIC_NAME


class KeyboardListenerSubscriber:
    def __init__(
        self,
        topic_name: str = KEYBOARD_LISTENER_TOPIC_NAME,
        node_name: str = "keyboard_listener_subscriber",
    ):
        assert rclpy.ok(), "Expected ROS2 to be initialized in this process..."
        self.node = ROSManager(node_name=node_name).node
        self.subscriber = self.node.create_subscription(RosStringMsg, topic_name, self._callback, 1)
        self._queue = deque()
        self._lock = threading.Lock()

    def _callback(self, msg: RosStringMsg) -> None:
        with self._lock:
            self._queue.append(msg.data)

    def read_msg(self):
        with self._lock:
            if not self._queue:
                return None
            return self._queue.popleft()


class KeyboardListenerPublisher:
    def __init__(
        self,
        topic_name: str = KEYBOARD_LISTENER_TOPIC_NAME,
        node_name: str = "keyboard_listener_publisher",
    ):
        assert rclpy.ok(), "Expected ROS2 to be initialized in this process..."
        self.node = ROSManager(node_name=node_name).node
        self.publisher = self.node.create_publisher(RosStringMsg, topic_name, 1)

    def publish(self, key: str) -> None:
        msg = RosStringMsg()
        msg.data = key
        self.publisher.publish(msg)
