from __future__ import annotations

import base64
import signal
import threading
import time
from typing import Optional

import msgpack
import msgpack_numpy as mnp
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
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
    _node = None
    _thread = None

    def __init__(self, node_name: str = "ros_manager"):
        if not rclpy.ok():
            rclpy.init()
        if ROSManager._node is None:
            ROSManager._node = rclpy.create_node(node_name)
            ROSManager._thread = threading.Thread(
                target=rclpy.spin, args=(ROSManager._node,), daemon=True
            )
            ROSManager._thread.start()
        self.node = ROSManager._node
        self.thread = ROSManager._thread
        register_keyboard_interrupt_handler()

    @staticmethod
    def ok() -> bool:
        return rclpy.ok()

    @staticmethod
    def shutdown() -> None:
        if rclpy.ok():
            rclpy.shutdown()
        ROSManager._node = None
        ROSManager._thread = None

    @staticmethod
    def exceptions():
        return (rclpy.exceptions.ROSInterruptException, KeyboardInterrupt)


class ROSMsgSubscriber:
    def __init__(
        self,
        topic_name: str,
        *,
        depth: int = 1,
        transient_local: bool = False,
        reliable: bool = False,
    ):
        ros_manager = ROSManager()
        self.node = ros_manager.node
        self._msg = None
        qos_profile = QoSProfile(depth=depth)
        if transient_local:
            qos_profile.durability = DurabilityPolicy.TRANSIENT_LOCAL
        if reliable:
            qos_profile.reliability = ReliabilityPolicy.RELIABLE

        self.subscription = self.node.create_subscription(
            ByteMultiArray, topic_name, self._callback, qos_profile
        )

    def _callback(self, msg: ByteMultiArray) -> None:
        self._msg = msg

    def get_msg(self) -> Optional[dict]:
        msg = self._msg
        if msg is None:
            return None
        self._msg = None
        return msgpack.unpackb(bytes([ab for a in msg.data for ab in a]), object_hook=mnp.decode)

    def wait_for_msg(self, timeout_sec: float | None = None, poll_sec: float = 0.05) -> Optional[dict]:
        deadline = None if timeout_sec is None else (time.monotonic() + timeout_sec)
        while True:
            msg = self.get_msg()
            if msg is not None:
                return msg
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(poll_sec)


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
