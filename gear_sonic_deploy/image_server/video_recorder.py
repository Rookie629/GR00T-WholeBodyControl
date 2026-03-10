# video_recorder.py
import os
import cv2
import argparse
from datetime import datetime
from src.image_server.image_client import ImageClient

def record(ip: str, port: int, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    client = ImageClient(image_show=False, server_address=ip, port=port)

    print(f"[Recorder] Recording to {out_dir}")
    try:
        while True:
            message = client._socket.recv()
            try:
                ts, frame_id, color, depth = client._decode_payload(message)
            except Exception as e:
                print(f"[Recorder] decode error: {e}")
                continue

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

            # 保存彩色图像
            color_path = os.path.join(out_dir, f"{timestamp}_color.jpg")
            cv2.imwrite(color_path, color)

            # 保存深度图
            if depth is not None:
                depth_path = os.path.join(out_dir, f"{timestamp}_depth.png")
                cv2.imwrite(depth_path, depth)

            print(f"[Recorder] Saved frame {frame_id} at {timestamp}")

    except KeyboardInterrupt:
        print("[Recorder] Stopped by user")
    finally:
        client._close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", type=str, default="127.0.0.1", help="Server IP address")
    parser.add_argument("--port", type=int, default=5555, help="Server port")
    parser.add_argument("--out", type=str, default="datasets/recordings", help="Output directory")
    args = parser.parse_args()

    record(args.ip, args.port, args.out)