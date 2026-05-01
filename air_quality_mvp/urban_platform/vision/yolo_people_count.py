from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class YoloPeopleCountConfig:
    camera_index: int = 0
    model: str = "yolov8n.pt"
    conf: float = 0.25
    iou: float = 0.45
    sample_fps: float = 2.0


def count_people_last_window(*, window_seconds: int = 5, cfg: Optional[YoloPeopleCountConfig] = None) -> int:
    """
    Count people for the last `window_seconds` using YOLO on the local camera.

    Notes:
    - Lazy-imports heavy deps (`ultralytics`, `cv2`) so the rest of the repo works without them.
    - This function does NOT persist frames; everything is in-memory.
    - Returns the max number of "person" detections across sampled frames in the window.
    """
    if int(window_seconds) <= 0:
        raise ValueError("window_seconds must be > 0")
    cfg = cfg or YoloPeopleCountConfig()

    try:
        import cv2  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("OpenCV is not installed. Install `opencv-python`.") from exc

    try:
        from ultralytics import YOLO  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Ultralytics YOLO is not installed. Install `ultralytics`.") from exc

    cap = cv2.VideoCapture(int(cfg.camera_index))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera index {cfg.camera_index}")

    model = YOLO(cfg.model)
    max_people = 0
    start = time.monotonic()
    next_sample = start
    sample_period = 1.0 / float(cfg.sample_fps) if float(cfg.sample_fps) > 0 else 0.0

    try:
        while True:
            now = time.monotonic()
            if now - start >= float(window_seconds):
                break
            if sample_period > 0 and now < next_sample:
                time.sleep(min(0.05, next_sample - now))
                continue
            next_sample = now + sample_period

            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            # Ultralytics returns a list of Results objects
            results = model.predict(frame, conf=float(cfg.conf), iou=float(cfg.iou), verbose=False)
            if not results:
                continue

            r0 = results[0]
            try:
                # class id 0 is "person" in COCO
                cls = r0.boxes.cls
                people = int((cls == 0).sum().item()) if cls is not None else 0
            except Exception:
                people = 0
            max_people = max(max_people, people)
    finally:
        try:
            cap.release()
        except Exception:
            pass

    return int(max_people)

