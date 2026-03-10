# -*- coding: utf-8 -*-
import cv2
import zmq
import numpy as np
import struct
from typing import Optional, Tuple
from multiprocessing import shared_memory
import argparse
import zlib

# 与服务器一致
HEADER_FMT = "<d I H H H H I I B"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
FLAG_DEPTH_PRESENT = 1 << 0
FLAG_DEPTH_ZLIB    = 1 << 1
FLAG_COLOR_JPEG    = 1 << 2


class ImageClient:
    def __init__(
        self,
        tv_img_shape: Optional[Tuple[int,int,int]] = None,
        tv_img_shm_name: Optional[str] = None,
        tv_dep_shape: Optional[Tuple[int,int]] = None,
        tv_dep_shm_name: Optional[str] = None,
        image_show: bool = True,
        server_address: str = "127.0.0.1",
        port: int = 5555,
    ):
        self.running = True
        self._image_show = image_show
        self.addr = server_address
        self.port = port

        self.tv_img_shape = tv_img_shape  # (H,W,3) 或 None -> 首帧确定
        self.tv_dep_shape = tv_dep_shape  # (H,W)   或 None -> 首帧确定

        # 共享内存（按需）
        self.tv_enable_img_shm = False
        if self.tv_img_shape is not None and tv_img_shm_name:
            self.tv_image_shm = shared_memory.SharedMemory(name=tv_img_shm_name)
            self.tv_img_array = np.ndarray(self.tv_img_shape, dtype=np.uint8, buffer=self.tv_image_shm.buf)
            self.tv_enable_img_shm = True

        self.tv_enable_dep_shm = False
        if self.tv_dep_shape is not None and tv_dep_shm_name:
            self.tv_depth_shm = shared_memory.SharedMemory(name=tv_dep_shm_name)
            self.tv_dep_array = np.ndarray(self.tv_dep_shape, dtype=np.uint16, buffer=self.tv_depth_shm.buf)
            self.tv_enable_dep_shm = True

        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.SUB)
        self._socket.setsockopt(zmq.RCVHWM, 3)
        self._socket.connect(f"tcp://{self.addr}:{self.port}")
        self._socket.setsockopt_string(zmq.SUBSCRIBE, "")

    def _close(self):
        try:
            self._socket.close(0)
            self._context.term()
        except Exception:
            pass
        if self._image_show:
            cv2.destroyAllWindows()
        print("[Image Client] closed")

    def _maybe_init_shm_from_first_frame(self, color: np.ndarray, depth: Optional[np.ndarray]) -> None:
        if self.tv_img_shape is None:
            self.tv_img_shape = color.shape
        if depth is not None and self.tv_dep_shape is None:
            self.tv_dep_shape = depth.shape

    def _write_shm(self, color: np.ndarray, depth: Optional[np.ndarray]) -> None:
        if self.tv_enable_img_shm:
            h, w = self.tv_img_shape[:2]  # type: ignore
            np.copyto(self.tv_img_array, color[:h, :w, :])
        if self.tv_enable_dep_shm and depth is not None and self.tv_dep_shape is not None:
            h, w = self.tv_dep_shape
            np.copyto(self.tv_dep_array, depth[:h, :w])

    def _decode_payload(self, payload: bytes):
        # 头部
        if len(payload) < HEADER_SIZE:
            raise ValueError("payload too small")
        ts, frame_id, cw, ch, dw, dh, csize, dsize, flags = struct.unpack(HEADER_FMT, payload[:HEADER_SIZE])
        offset = HEADER_SIZE

        # 颜色
        color_bytes = payload[offset: offset + csize]
        offset += csize
        if flags & FLAG_COLOR_JPEG:
            np_img = np.frombuffer(color_bytes, dtype=np.uint8)
            color = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
        else:
            color = np.frombuffer(color_bytes, dtype=np.uint8).reshape((ch, cw, 3))

        # 深度（可选）
        depth = None
        if flags & FLAG_DEPTH_PRESENT:
            depth_bytes = payload[offset: offset + dsize]
            if flags & FLAG_DEPTH_ZLIB:
                depth_raw = zlib.decompress(depth_bytes)
            else:
                depth_raw = depth_bytes
            depth = np.frombuffer(depth_raw, dtype=np.uint16).reshape((dh, dw))

        return ts, frame_id, color, depth

    def receive_process(self):
        print(f"[Image Client] connecting tcp://{self.addr}:{self.port} ...")
        try:
            while self.running:
                message = self._socket.recv()
                try:
                    ts, frame_id, color, depth = self._decode_payload(message)
                except Exception as e:
                    print(f"[Image Client] decode error: {e}")
                    continue

                if color is None:
                    continue

                # 首帧决定共享内存布局（若未指定）
                self._maybe_init_shm_from_first_frame(color, depth)

                # 写共享内存
                self._write_shm(color, depth)

                # 可视化
                if self._image_show:
                    if depth is not None:
                        depth_vis = cv2.applyColorMap(cv2.convertScaleAbs(depth, alpha=0.03), cv2.COLORMAP_JET)
                        if depth_vis.shape[:2] != color.shape[:2]:
                            depth_vis = cv2.resize(depth_vis, (color.shape[1], color.shape[0]))
                        show = np.hstack([color, depth_vis])
                    else:
                        show = color
                    cv2.imshow("RGB | Depth", show)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        self.running = False

        except KeyboardInterrupt:
            print("[Image Client] interrupted")
        finally:
            self._close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", type=str, default="127.0.0.1", help="Server IP address")
    parser.add_argument("--port", type=int, default=5555, help="Server port")
    args = parser.parse_args()
    
    # 示例：只显示（无需共享内存）
    client = ImageClient(image_show=True, server_address=args.ip, port=args.port)
    client.receive_process()