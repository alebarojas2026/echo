"""App Lab entry point. Run only the teacher inside the container."""

import json
import os
from pathlib import Path
import socket

from labels import Projection, Teacher, attach_processed_results, read_mode
from heartbeat import write_heartbeat


def main():
    from arduino.app_bricks.video_objectdetection import VideoObjectDetection
    from arduino.app_utils import App

    calibration = Path(os.environ.get("TEACHER_CALIB", "calib.json"))
    mode_file = os.environ.get("TEACHER_MODE_FILE", "label_mode")
    heartbeat_file = os.environ["TEACHER_HEARTBEAT"]
    projection = Projection(json.loads(calibration.read_text()))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        def send(label):
            udp.sendto(json.dumps(label, allow_nan=False).encode(), ("msgpack-rpc-router", 5600))
            write_heartbeat(heartbeat_file, label)

        detector = VideoObjectDetection(confidence=0.4, debounce_sec=0.0, camera_preview=False)
        teacher = Teacher(projection, send, mode=lambda: read_mode(mode_file))
        attach_processed_results(detector, teacher)
        App.run()


if __name__ == "__main__":
    main()
