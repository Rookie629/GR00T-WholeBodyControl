from __future__ import annotations

import base64
import signal
import threading
from typing import Optional

import msgpack
import msgpack_numpy as mnp
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import ByteMultiArray
from std_srvs.srv import Trigger

_signal_registered = False


def register_keyboard_interrupt_handler() -> None:
    global _signal_registered
    if not _signal_registered:

        def signal_handler(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        _signal_registered = True


class ROSManager:
    def __init__(self, node_name: str = "ros_manager"):
        if not rclpy.ok():
            rclpy.init()
            self.node = rclpy.create_node(node_name)
            self.thread = threading.Thread(target=rclpy.spin, args=(self.node,), daemon=True)
            self.thread.start()
        else:
            executor = rclpy.get_global_executor()
            if len(executor.get_nodes()) > 0:
                self.node = executor.get_nodes()[0]
            else:
                self.node = rclpy.create_node(node_name)
        register_keyboard_interrupt_handler()

    @staticmethod
    def ok() -> bool:
        return rclpy.ok()

    @staticmethod
    def shutdown() -> None:
        if rclpy.ok():
            rclpy.shutdown()

    @staticmethod
    def exceptions():
        return (rclpy.exceptions.ROSInterruptException, KeyboardInterrupt)


class ROSMsgSubscriber:
    def __init__(self, topic_name: str):
        ros_manager = ROSManager()
        self.node = ros_manager.node
        self._msg = None
        self.subscription = self.node.create_subscription(ByteMultiArray, topic_name, self._callback, 1)

    def _callback(self, msg: ByteMultiArray) -> None:
        self._msg = msg

    def get_msg(self) -> Optional[dict]:
        msg = self._msg
        if msg is None:
            return None
        self._msg = None
        return msgpack.unpackb(bytes([ab for a in msg.data for ab in a]), object_hook=mnp.decode)


class ROSServiceClient(Node):
    def __init__(self, service_name: str, node_name: str = "service_client"):
        super().__init__(node_name)
        self.cli = self.create_client(Trigger, service_name)
        while not self.cli.wait_for_service(timeout_sec=1.0):
            self.get_logger().info("service not available, waiting again...")
        self.req = Trigger.Request()

    def get_config(self):
        future = self.cli.call_async(self.req)
        executor = SingleThreadedExecutor()
        executor.add_node(self)
        executor.spin_until_future_complete(future, timeout_sec=1.0)
        executor.remove_node(self)
        executor.shutdown()
        result = future.result()
        if result.success:
            decoded = base64.b64decode(result.message.encode("ascii"))
            return msgpack.unpackb(decoded, object_hook=mnp.decode)
        raise RuntimeError(f"Service call failed: {result.message}")
