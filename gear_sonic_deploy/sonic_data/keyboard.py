from __future__ import annotations

import rclpy
from std_msgs.msg import String as RosStringMsg

from gear_sonic_deploy.sonic_data.topics import KEYBOARD_LISTENER_TOPIC_NAME


class KeyboardListenerSubscriber:
    def __init__(
        self,
        topic_name: str = KEYBOARD_LISTENER_TOPIC_NAME,
        node_name: str = "keyboard_listener_subscriber",
    ):
        assert rclpy.ok(), "Expected ROS2 to be initialized in this process..."
        executor = rclpy.get_global_executor()
        nodes = executor.get_nodes()
        if nodes:
            self.node = nodes[0]
        else:
            self.node = rclpy.create_node(node_name)
            executor.add_node(self.node)
        self.subscriber = self.node.create_subscription(RosStringMsg, topic_name, self._callback, 1)
        self._data = None

    def _callback(self, msg: RosStringMsg) -> None:
        self._data = msg.data

    def read_msg(self):
        data = self._data
        self._data = None
        return data
