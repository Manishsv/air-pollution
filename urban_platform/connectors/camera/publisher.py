from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Callable, Optional

from urban_platform.connectors.camera.laptop_camera import PeopleCountProvenance, read_people_count_feed


def _sleep_until(deadline_monotonic_s: float) -> None:
    while True:
        now = time.monotonic()
        remaining = deadline_monotonic_s - now
        if remaining <= 0:
            return
        time.sleep(min(remaining, 1.0))


def _append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, default=str, allow_nan=False)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def run_people_count_file_publisher(
    *,
    device_id: str,
    out_path: Path,
    publish_every_seconds: int = 300,
    sample_window_seconds: int = 5,
    provenance: PeopleCountProvenance = PeopleCountProvenance(model_name="placeholder_people_counter"),
    count_people_for_window: Optional[Callable[[int], int]] = None,
) -> None:
    """
    Run forever, emitting a provider-contract payload as JSONL on a schedule.

    Every `publish_every_seconds`:
      - compute a people count for the last `sample_window_seconds`
      - wrap it into the provider feed contract via `read_people_count_feed`
      - append one JSON object as a single line to `out_path`

    Notes:
    - This does not store frames; it only stores derived counts + provenance.
    - `count_people_for_window` is a pluggable callback. For now, a default
      placeholder returns 0.
    """
    if int(publish_every_seconds) <= 0:
        raise ValueError("publish_every_seconds must be > 0")
    if int(sample_window_seconds) != 5:
        # Our v1 provider schema currently fixes window_seconds=5 (Option A).
        raise ValueError("sample_window_seconds must be 5 to match the v1 provider contract")

    def _default_counter(_window_seconds: int) -> int:
        del _window_seconds
        return 0

    counter = count_people_for_window or _default_counter

    next_emit = time.monotonic()
    while True:
        next_emit += float(publish_every_seconds)

        # Compute for the last 5 seconds (implementation lives in the callback).
        count = int(counter(int(sample_window_seconds)))
        feed = read_people_count_feed(
            device_id=device_id,
            window_seconds=int(sample_window_seconds),
            provenance=provenance,
            count_people=lambda: count,
        )
        _append_jsonl(out_path, feed)

        _sleep_until(next_emit)


def _main() -> None:
    ap = argparse.ArgumentParser(description="Edge publisher: laptop camera people count -> JSONL (provider contract)")
    ap.add_argument("--device-id", required=True)
    ap.add_argument("--out", default="data/edge/video_camera_people_count.jsonl")
    ap.add_argument("--publish-every-seconds", type=int, default=300)
    ap.add_argument("--use-yolo", action="store_true", help="Use YOLO (ultralytics + opencv) to count people from the local camera")
    ap.add_argument("--camera-index", type=int, default=0, help="OpenCV camera index (default 0)")
    ap.add_argument("--yolo-model", default="yolov8n.pt", help="Ultralytics model name or path (default yolov8n.pt)")
    ap.add_argument("--yolo-conf", type=float, default=0.25, help="YOLO confidence threshold")
    ap.add_argument("--yolo-iou", type=float, default=0.45, help="YOLO IoU threshold")
    ap.add_argument("--sample-fps", type=float, default=2.0, help="FPS to sample during the 5-second window")
    args = ap.parse_args()

    counter = None
    provenance = PeopleCountProvenance(model_name="placeholder_people_counter")
    if bool(args.use_yolo):
        from urban_platform.vision.yolo_people_count import YoloPeopleCountConfig, count_people_last_window

        cfg = YoloPeopleCountConfig(
            camera_index=int(args.camera_index),
            model=str(args.yolo_model),
            conf=float(args.yolo_conf),
            iou=float(args.yolo_iou),
            sample_fps=float(args.sample_fps),
        )

        def _counter(window_seconds: int) -> int:
            return int(count_people_last_window(window_seconds=window_seconds, cfg=cfg))

        counter = _counter
        provenance = PeopleCountProvenance(model_name="yolo", model_version=str(args.yolo_model), inference_device="local")

    run_people_count_file_publisher(
        device_id=str(args.device_id),
        out_path=Path(args.out),
        publish_every_seconds=int(args.publish_every_seconds),
        sample_window_seconds=5,
        provenance=provenance,
        count_people_for_window=counter,
    )


if __name__ == "__main__":
    _main()

