# -*- coding: utf-8 -*-
import cv2
import zmq
import time
import struct
from collections import deque
from typing import List, Optional, Tuple
import numpy as np
import zlib

try:
    import pyrealsense2 as rs
    HAS_RS = True
except Exception:
    HAS_RS = False


# ======= 常量与协议 =======
# 统一消息头（小端）：ts, frame_id, color_w,h, depth_w,h, color_size, depth_size, flags
# flags: bit0=depth_present, bit1=depth_zlib, bit2=color_jpeg
HEADER_FMT = "<d I H H H H I I B"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
FLAG_DEPTH_PRESENT = 1 << 0
FLAG_DEPTH_ZLIB    = 1 << 1
FLAG_COLOR_JPEG    = 1 << 2

# 放在文件顶部其他 import 之后
def _list_realsense_serials():
    try:
        import pyrealsense2 as rs
    except Exception:
        return []
    ctx = rs.context()
    serials = []
    for d in ctx.devices:
        try:
            serials.append(d.get_info(rs.camera_info.serial_number))
        except Exception:
            pass
    return serials

# ======= 摄像头抽象 =======
class CameraBase:
    def get_frame(self) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """返回 (color[BGR uint8 HxWx3], depth[uint16 HxW] or None)"""
        raise NotImplementedError
    def release(self) -> None:
        pass
    @property
    def shape(self) -> Tuple[int, int]:
        raise NotImplementedError


class RealSenseCamera(CameraBase):
    def __init__(self, img_shape: Tuple[int, int], fps: int, serial_number: Optional[str] = None, enable_depth: bool = True) -> None:
        if not HAS_RS:
            raise RuntimeError("pyrealsense2 未安装，无法使用 RealSense 相机。")
        self.img_shape = img_shape  # (H, W)
        self.fps = fps
        self.serial_number = serial_number
        self.enable_depth = enable_depth

        align_to = rs.stream.color
        self.align = rs.align(align_to)
        self.pipeline = rs.pipeline()
        config = rs.config()
        if self.serial_number:
            config.enable_device(self.serial_number)
        config.enable_stream(rs.stream.color, self.img_shape[1], self.img_shape[0], rs.format.bgr8, self.fps)
        if self.enable_depth:
            config.enable_stream(rs.stream.depth, self.img_shape[1], self.img_shape[0], rs.format.z16, self.fps)
        profile = self.pipeline.start(config)
        self._device = profile.get_device()
        if self.enable_depth:
            depth_sensor = self._device.first_depth_sensor()
            self.g_depth_scale = depth_sensor.get_depth_scale()
        self.intrinsics = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()

    @property
    def shape(self) -> Tuple[int, int]:
        return self.img_shape

    def get_frame(self) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        frames = self.pipeline.wait_for_frames()
        aligned = self.align.process(frames)
        color_frame = aligned.get_color_frame()
        if not color_frame:
            return None, None  # type: ignore
        color = np.asanyarray(color_frame.get_data())
        depth = None
        if self.enable_depth:
            depth_frame = aligned.get_depth_frame()
            if depth_frame:
                depth = np.asanyarray(depth_frame.get_data())
        return color, depth

    def release(self) -> None:
        try:
            self.pipeline.stop()
        except Exception:
            pass


class OpenCVCamera(CameraBase):
    def __init__(self, device_id: int, img_shape: Tuple[int, int], fps: int):
        self.id = device_id
        self.fps = fps
        self.img_shape = img_shape
        self.cap = cv2.VideoCapture(self.id, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc('M','J','P','G'))
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.img_shape[0])
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.img_shape[1])
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        ok, _ = self.cap.read()
        if not ok:
            raise RuntimeError(f"OpenCVCamera 初始化失败：/dev/video{self.id}")

    @property
    def shape(self) -> Tuple[int, int]:
        return self.img_shape

    def get_frame(self) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        ret, color = self.cap.read()
        if not ret or color is None:
            return None, None  # type: ignore
        return color, None

    def release(self) -> None:
        try:
            self.cap.release()
        except Exception:
            pass


# ======= 服务器 =======
class ImageServer:
    def __init__(self, config: dict, port: int = 5555, with_metrics: bool = False):
        """
        config示例：
        {
          'fps':30,
          'head_camera_type':'realsense',  # 'opencv' | 'realsense'
          'head_camera_image_shape':[480,640],
          'head_camera_id_numbers':["233622077862"],  # RS序列号 或 opencv索引
          'wrist_camera_type':'opencv',
          'wrist_camera_image_shape':[480,640],
          'wrist_camera_id_numbers':[0,1],
        }
        """
        self.fps = int(config.get('fps', 30))
        self.port = int(port)
        self.with_metrics = with_metrics

        self.head_camera_type = config.get('head_camera_type', 'opencv')
        self.head_image_shape = tuple(config.get('head_camera_image_shape', [480, 640]))
        self.head_ids = config.get('head_camera_id_numbers', None)

        self.wrist_camera_type = config.get('wrist_camera_type', None)
        self.wrist_image_shape = tuple(config.get('wrist_camera_image_shape', [480, 640]))
        self.wrist_ids = config.get('wrist_camera_id_numbers', None)

        self.head_cams: List[CameraBase] = []
        self.wrist_cams: List[CameraBase] = []

        # 初始化相机
        self._init_cameras()

        # ZeroMQ
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.setsockopt(zmq.SNDHWM, 3)  # 丢旧帧以降低延迟
        self.socket.bind(f"tcp://*:{self.port}")

        if self.with_metrics:
            self._init_metrics()

        print(f"[Image Server] started on tcp://*:{self.port}")

    def _init_cameras(self) -> None:
        # ---------- 解析 head ids ----------
        if self.head_camera_type == 'realsense':
            # 如果未显式提供序列号，则自动发现
            if not self.head_ids or len(self.head_ids) == 0:
                serials = _list_realsense_serials()
                if len(serials) == 0:
                    raise RuntimeError("[Image Server] 未发现任何 RealSense 设备，请检查连接。")
                if len(serials) > 1:
                    # 如需自动选第一台，可以把下面的 raise 替换为 self.head_ids = [serials[0]]
                    raise RuntimeError(f"[Image Server] 发现多台 RealSense:{serials}。"
                                    f"请在 head_camera_id_numbers 中指定一个序列号。")
                self.head_ids = [serials[0]]
                print(f"[Image Server] 自动选择唯一 RealSense: {self.head_ids[0]}")

        # ---------- 解析 wrist ids ----------
        if self.wrist_camera_type == 'realsense' and (not self.wrist_ids or len(self.wrist_ids) == 0):
            serials = _list_realsense_serials()
            if len(serials) == 0:
                raise RuntimeError("[Image Server] 未发现任何 RealSense 设备（用于腕部）。")
            if len(serials) > 1:
                raise RuntimeError(f"[Image Server] 腕部发现多台 RealSense:{serials}。"
                                f"请在 wrist_camera_id_numbers 中指定序列号。")
            self.wrist_ids = [serials[0]]
            print(f"[Image Server] 自动选择腕部 RealSense: {self.wrist_ids[0]}")

        # ---------- 头部相机实例化 ----------
        if self.head_camera_type == 'opencv':
            for dev in self.head_ids:
                self.head_cams.append(OpenCVCamera(device_id=int(dev), img_shape=self.head_image_shape, fps=self.fps))
        elif self.head_camera_type == 'realsense':
            for sn in self.head_ids:
                self.head_cams.append(RealSenseCamera(img_shape=self.head_image_shape, fps=self.fps,
                                                    serial_number=str(sn), enable_depth=True))
        else:
            raise ValueError(f"Unsupported head type: {self.head_camera_type}")

        # ---------- 腕部相机（可选） ----------
        if self.wrist_camera_type and self.wrist_ids:
            if self.wrist_camera_type == 'opencv':
                for dev in self.wrist_ids:
                    self.wrist_cams.append(OpenCVCamera(device_id=int(dev), img_shape=self.wrist_image_shape, fps=self.fps))
            elif self.wrist_camera_type == 'realsense':
                for sn in self.wrist_ids:
                    self.wrist_cams.append(RealSenseCamera(img_shape=self.wrist_image_shape, fps=self.fps,
                                                        serial_number=str(sn), enable_depth=True))
            else:
                raise ValueError(f"Unsupported wrist type: {self.wrist_camera_type}")

        # ---------- 打印分辨率 ----------
        for cam in self.head_cams + self.wrist_cams:
            h, w = cam.shape
            print(f"[Image Server] camera ready: {cam.__class__.__name__} {w}x{h}")

    def _init_metrics(self) -> None:
        self.frame_id = 0
        self.t0 = time.time()
        self.window = deque(maxlen=60)

    def _update_metrics(self) -> None:
        if not self.with_metrics:
            return
        now = time.time()
        self.window.append(now)
        if self.frame_id % 60 == 0 and len(self.window) > 1:
            fps = (len(self.window)-1) / (self.window[-1] - self.window[0])
            print(f"[Image Server] fps ~ {fps:.1f}")

    def _gather_frames(self) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """拼接头/腕彩色与深度（如有）。返回full_color, full_depth."""
        head_colors, head_depths = [], []
        for cam in self.head_cams:
            color, depth = cam.get_frame()
            if color is None:
                raise RuntimeError("Head camera read failed")
            head_colors.append(color)
            head_depths.append(depth)

        color_concat_head = cv2.hconcat(head_colors) if len(head_colors) > 1 else head_colors[0]
        depth_concat_head = None
        if any(d is not None for d in head_depths):
            # 没深度的填零，保证拼接
            fixed = [(d if d is not None else np.zeros(head_colors[i].shape[:2], np.uint16))
                     for i, d in enumerate(head_depths)]
            depth_concat_head = cv2.hconcat(fixed) if len(fixed) > 1 else fixed[0]

        full_color = color_concat_head
        full_depth = depth_concat_head

        if self.wrist_cams:
            wrist_colors, wrist_depths = [], []
            for cam in self.wrist_cams:
                color, depth = cam.get_frame()
                if color is None:
                    raise RuntimeError("Wrist camera read failed")
                wrist_colors.append(color)
                wrist_depths.append(depth)

            color_concat_wrist = cv2.hconcat(wrist_colors) if len(wrist_colors) > 1 else wrist_colors[0]
            full_color = cv2.hconcat([color_concat_head, color_concat_wrist])

            if any(d is not None for d in wrist_depths):
                fixed = [(d if d is not None else np.zeros(wrist_colors[i].shape[:2], np.uint16))
                         for i, d in enumerate(wrist_depths)]
                depth_concat_wrist = cv2.hconcat(fixed) if len(fixed) > 1 else fixed[0]
                if full_depth is None:
                    full_depth = np.zeros_like(depth_concat_head if depth_concat_head is not None else depth_concat_wrist)
                full_depth = cv2.hconcat([full_depth, depth_concat_wrist]) if full_depth is not None else depth_concat_wrist

        return full_color, full_depth

    def _encode_and_send(self, color: np.ndarray, depth: Optional[np.ndarray], frame_id: int) -> None:
        # JPEG颜色
        ok, buf = cv2.imencode(".jpg", color, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            return
        color_bytes = buf.tobytes()
        h_c, w_c = color.shape[:2]

        flags = FLAG_COLOR_JPEG
        depth_bytes = b""
        h_d, w_d = 0, 0
        if depth is not None:
            h_d, w_d = depth.shape[:2]
            flags |= FLAG_DEPTH_PRESENT | FLAG_DEPTH_ZLIB
            depth_bytes = zlib.compress(depth.tobytes())

        header = struct.pack(
            HEADER_FMT,
            time.time(), frame_id,
            w_c, h_c, w_d, h_d,
            len(color_bytes), len(depth_bytes), flags
        )
        self.socket.send(header + color_bytes + depth_bytes)

    def close(self) -> None:
        for cam in self.head_cams + self.wrist_cams:
            cam.release()
        try:
            self.socket.close(0)
            self.context.term()
        except Exception:
            pass
        print("[Image Server] closed")

    def run(self) -> None:
        try:
            frame_id = 0
            while True:
                color, depth = self._gather_frames()
                self._encode_and_send(color, depth, frame_id)
                frame_id += 1
                self._update_metrics()
        except KeyboardInterrupt:
            print("[Image Server] interrupted")
        except Exception as e:
            print(f"[Image Server] error: {e}")
        finally:
            self.close()


if __name__ == "__main__":
    cfg = {
        'fps': 30,
        'head_camera_type': 'realsense',  # 'opencv' or 'realsense'
        'head_camera_image_shape': [480, 640],
        # 'head_camera_id_numbers': None,  # 可省略，会自动寻找唯一rs设备
    }
    server = ImageServer(cfg, port=5555, with_metrics=False)
    server.run()
    
    # 示例配置模板（cfg），可根据实际相机类型和数量修改
    # 说明：
    # - fps: 帧率，建议30
    # - head_camera_type: 头部相机类型，'opencv'（普通USB摄像头）或'realsense'
    # - head_camera_image_shape: 头部相机分辨率，[高, 宽]
    # - head_camera_id_numbers: 头部相机编号，realsense为序列号（字符串），opencv为设备号（整数），如只有一台可省略自动检测
    # - wrist_camera_type: 腕部相机类型（可选），同上
    # - wrist_camera_image_shape: 腕部相机分辨率（可选），同上
    # - wrist_camera_id_numbers: 腕部相机编号（可选），同上
    #
    # 示例（仅头部realsense）：
    # cfg = {
    #     'fps': 30,
    #     'head_camera_type': 'realsense',           # 'opencv' 或 'realsense'
    #     'head_camera_image_shape': [480, 640],
    #     # 'head_camera_id_numbers': ["233622077862"], # 可省略，会自动寻找唯一rs设备
    # }
    #
    # 示例（头部realsense+腕部opencv）：
    # cfg = {
    #     'fps': 30,
    #     'head_camera_type': 'realsense',
    #     'head_camera_image_shape': [480, 640],
    #     # 'head_camera_id_numbers': ["233622077862"],
    #     'wrist_camera_type': 'opencv',
    #     'wrist_camera_image_shape': [480, 640],
    #     'wrist_camera_id_numbers': [0],  # /dev/video0
    # }
