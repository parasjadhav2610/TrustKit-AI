"""TrustKit AI — Frame Extractor Module.

Responsible for extracting frames from:
- live video streams (via WebSocket buffer)
- uploaded video files (via file path)

Uses OpenCV for real frame extraction.
"""

from __future__ import annotations

import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple

import cv2  # type: ignore


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ExtractedFrame:
    """Metadata for a single extracted frame."""

    index: int
    timestamp_sec: float
    file_path: str

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "timestamp_sec": self.timestamp_sec,
            "file_path": self.file_path,
        }


@dataclass
class ExtractionSummary:
    """Summary of an extraction run."""

    session_id: str
    video_path: str
    output_dir: str
    total_frames_in_video: int
    fps: float
    duration_sec: float
    sampled_every_n_frames: int
    requested_interval_sec: float
    extracted_count: int
    limit_hit: bool
    frames: List[ExtractedFrame]

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "video_path": self.video_path,
            "output_dir": self.output_dir,
            "total_frames_in_video": self.total_frames_in_video,
            "fps": self.fps,
            "duration_sec": self.duration_sec,
            "sampled_every_n_frames": self.sampled_every_n_frames,
            "requested_interval_sec": self.requested_interval_sec,
            "limit_hit": self.limit_hit,
            "extracted_count": self.extracted_count,
            "frames": [frame.to_dict() for frame in self.frames],
        }


class FrameExtractionError(Exception):
    """Raised when frame extraction fails."""


# ---------------------------------------------------------------------------
# Core extractor class
# ---------------------------------------------------------------------------``


class FrameExtractor:
    """
    Extract representative frames from a video.

    Typical usage:
        extractor = FrameExtractor(output_root="tmp/frames")
        result = extractor.extract(
            video_path="sample_videos/tour.mp4",
            session_id="demo_001",
            interval_sec=1.0,
            max_frames=30,
            resize_width=1280,
        )

    Notes:
    - Uses OpenCV only, so it stays lightweight for hackathon usage.
    - Saves JPEG frames with predictable names.
    - Returns both per-frame metadata and run summary.
    """

    def __init__(self, output_root: str = "tmp/frames") -> None:
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)

    def extract(
        self,
        video_path: str,
        session_id: str,
        interval_sec: float = 1.0,
        max_frames: Optional[int] = 60,
        resize_width: Optional[int] = None,
        jpeg_quality: int = 90,
    ) -> ExtractionSummary:
        """
        Extract frames from a video at a fixed time interval.

        Args:
            video_path: Path to input video.
            session_id: Unique ID to isolate output frames for a request/session.
            interval_sec: Time gap between saved frames.
            max_frames: Hard cap on number of extracted frames.
            resize_width: If provided, resize frames to this width while preserving aspect ratio.
            jpeg_quality: JPEG save quality from 0 to 100.

        Returns:
            ExtractionSummary containing extracted frame metadata.
        """
        if interval_sec <= 0:
            raise ValueError("interval_sec must be > 0")
        if max_frames is not None and max_frames <= 0:
            raise ValueError("max_frames must be > 0 when provided")
        if not (0 <= jpeg_quality <= 100):
            raise ValueError("jpeg_quality must be between 0 and 100")

        video_file = Path(video_path)
        if not video_file.exists() or not video_file.is_file():
            raise FrameExtractionError(f"Video not found: {video_path}")

        output_dir = self.output_root / session_id
        output_dir.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(str(video_file))
        if not cap.isOpened():
            raise FrameExtractionError(f"Could not open video: {video_path}")

        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

            if fps <= 0:
                raise FrameExtractionError("Could not determine FPS for video")

            duration_sec = total_frames / fps if total_frames > 0 else 0.0
            sample_every_n = max(1, int(round(interval_sec * fps)))

            extracted: List[ExtractedFrame] = []
            frame_idx: int = 0
            saved_count: int = 0

            # Resolve Optionals early for strict type checking
            _resize_width: int = resize_width if resize_width is not None else 0
            _max_frames: int = max_frames if max_frames is not None else 0

            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                should_save = (frame_idx % sample_every_n) == 0  # type: ignore
                if should_save:
                    timestamp_sec = frame_idx / fps  # type: ignore

                    if _resize_width > 0:
                        frame = self._resize_keep_aspect(frame, _resize_width)

                    filename = f"frame_{saved_count:04d}_t{timestamp_sec:08.2f}.jpg"
                    file_path = output_dir / filename

                    success = cv2.imwrite(
                        str(file_path),
                        frame,
                        [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality],
                    )
                    if not success:
                        raise FrameExtractionError(f"Failed to save frame: {file_path}")

                    extracted.append(
                        ExtractedFrame(
                            index=frame_idx,  # type: ignore
                            timestamp_sec=round(timestamp_sec, 3),
                            file_path=str(file_path),
                        )
                    )
                    saved_count += 1  # type: ignore

                    if _max_frames > 0 and saved_count >= _max_frames:
                        break

                frame_idx += 1  # type: ignore

            limit_hit = _max_frames > 0 and saved_count >= _max_frames
            summary = ExtractionSummary(
                session_id=session_id,
                video_path=str(video_file),
                output_dir=str(output_dir),
                total_frames_in_video=total_frames,
                fps=round(fps, 3),  # type: ignore
                duration_sec=round(duration_sec, 3),  # type: ignore
                sampled_every_n_frames=sample_every_n,
                requested_interval_sec=interval_sec,
                extracted_count=len(extracted),
                limit_hit=limit_hit,
                frames=extracted,
            )
        finally:
            cap.release()

        return summary

    def iter_frames(
        self,
        video_path: str,
        interval_sec: float = 1.0,
        resize_width: Optional[int] = None,
    ) -> Iterator[Tuple[int, float, Any]]:
        """
        Yield frames in-memory instead of saving them.

        Useful if a downstream analyzer wants raw OpenCV images directly.
        Yields:
            (frame_index, timestamp_sec, frame_ndarray)
        """
        if interval_sec <= 0:
            raise ValueError("interval_sec must be > 0")

        video_file = Path(video_path)
        if not video_file.exists() or not video_file.is_file():
            raise FrameExtractionError(f"Video not found: {video_path}")

        cap = cv2.VideoCapture(str(video_file))
        if not cap.isOpened():
            raise FrameExtractionError(f"Could not open video: {video_path}")

        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            if fps <= 0:
                raise FrameExtractionError("Could not determine FPS for video")

            sample_every_n: int = max(1, int(round(interval_sec * fps)))
            frame_idx: int = 0

            # Resolve Optionals early for strict type checking
            _resize_width: int = resize_width if resize_width is not None else 0

            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                if (frame_idx % sample_every_n) == 0:  # type: ignore
                    timestamp_sec = frame_idx / fps  # type: ignore
                    if _resize_width > 0:
                        frame = self._resize_keep_aspect(frame, _resize_width)
                    yield frame_idx, round(timestamp_sec, 3), frame  # type: ignore

                frame_idx += 1  # type: ignore
        finally:
            cap.release()

    @staticmethod
    def _resize_keep_aspect(frame: Any, target_width: int) -> Any:
        height, width = frame.shape[:2]
        if width <= target_width:
            return frame

        scale = target_width / float(width)
        target_height = max(1, int(math.ceil(height * scale)))
        return cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)


# ---------------------------------------------------------------------------
# Backward-compatible convenience functions
# ---------------------------------------------------------------------------
# These preserve the original module API so that existing imports in
# main.py (extract_from_stream) and deep_scan.py (extract_from_file)
# continue to work without any changes.

# Shared extractor instance used by the convenience functions
_default_extractor = FrameExtractor(output_root="tmp/frames")


def extract_from_stream(buffer: bytes) -> list[bytes]:
    """Extract frames from a live video stream buffer.

    Writes the buffer to a temporary file, uses FrameExtractor.iter_frames
    to decode real frames via OpenCV, and returns them as JPEG-encoded bytes.

    Args:
        buffer: Raw binary data received from the WebSocket stream.

    Returns:
        A list of JPEG-encoded frame byte-buffers.
    """
    import os

    # Write buffer to a temp file so OpenCV can open it
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
        tmp.write(buffer)
        tmp_path = tmp.name

    result: list[bytes] = [buffer]
    try:
        encoded_frames: list[bytes] = []
        for _idx, _ts, frame in _default_extractor.iter_frames(tmp_path, interval_sec=1.0):
            ok, jpg = cv2.imencode(".jpg", frame)
            if ok:
                encoded_frames.append(jpg.tobytes())
        result = encoded_frames if encoded_frames else [b""]
    except FrameExtractionError:
        # If decoding fails (e.g. buffer is a single raw frame, not a video),
        # return the raw buffer as-is so the caller still gets data.
        result = [buffer]
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return result


def extract_from_file(video_path: str, num_frames: int = 7) -> list[bytes]:
    """Extract a specific number of evenly spaced frames from an uploaded video file.

    Args:
        video_path: Absolute path to the video file on disk.
        num_frames: The exact number of frames to extract (evenly spaced).

    Returns:
        A list of JPEG-encoded frame byte-buffers sampled from the video.
    """
    video_file = Path(video_path)
    if not video_file.exists() or not video_file.is_file():
        raise FrameExtractionError(f"Video not found: {video_path}")

    cap = cv2.VideoCapture(str(video_file))
    if not cap.isOpened():
        raise FrameExtractionError(f"Could not open video: {video_path}")

    encoded_frames: list[bytes] = []
    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total_frames <= 0:
            return encoded_frames
            
        # Calculate exactly which frame indices we want to grab
        # e.g., if total=300 and num=7, grab [0, 50, 100, 150, 200, 250, 299]
        if total_frames <= num_frames:
            target_indices = list(range(total_frames))
        else:
            step = max(1, total_frames / num_frames)
            target_indices = [int(i * step) for i in range(num_frames)]
            # ensure last index does not exceed bounds
            if target_indices[-1] >= total_frames:
                target_indices[-1] = total_frames - 1

        for target_idx in target_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_idx)
            ok, frame = cap.read()
            if ok:
                ok_encode, jpg = cv2.imencode(".jpg", frame)
                if ok_encode:
                    encoded_frames.append(jpg.tobytes())

    finally:
        cap.release()
        
    return encoded_frames


# ---------------------------------------------------------------------------
# CLI quick-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    extractor = FrameExtractor(output_root="tmp/frames")
    summary = extractor.extract(
        video_path="sample_videos/demo.mp4",
        session_id="local_test",
        interval_sec=1.0,
        max_frames=12,
        resize_width=1280,
    )
    print(summary.to_dict())
