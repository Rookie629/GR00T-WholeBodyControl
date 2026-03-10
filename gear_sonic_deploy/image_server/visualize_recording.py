# visualize_recording.py
import os
import cv2
import argparse
import numpy as np

def visualize(data_dir: str):
    files = sorted(os.listdir(data_dir))
    color_files = [f for f in files if f.endswith("_color.jpg")]

    for color_file in color_files:
        prefix = color_file.replace("_color.jpg", "")
        depth_file = prefix + "_depth.png"

        color_path = os.path.join(data_dir, color_file)
        color = cv2.imread(color_path)

        if os.path.exists(os.path.join(data_dir, depth_file)):
            depth = cv2.imread(os.path.join(data_dir, depth_file), cv2.IMREAD_UNCHANGED)
            depth_vis = cv2.applyColorMap(cv2.convertScaleAbs(depth, alpha=0.03), cv2.COLORMAP_JET)
            if depth_vis.shape[:2] != color.shape[:2]:
                depth_vis = cv2.resize(depth_vis, (color.shape[1], color.shape[0]))
            show = np.hstack([color, depth_vis])
        else:
            show = color

        cv2.imshow("Recorded RGB | Depth", show)
        if cv2.waitKey(100) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, default="datasets/recordings", help="Path to recorded data directory")
    args = parser.parse_args()

    visualize(args.data)