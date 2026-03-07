"""TrustKit AI — Frame Extractor Module.

Responsible for extracting frames from:
- live video streams (via WebSocket buffer)
- uploaded video files (via file path)

Libraries (for real implementation):
- OpenCV
- FFmpeg

Currently returns **mock data** so the frontend can be developed
in parallel.
"""


def extract_from_stream(buffer: bytes) -> list[bytes]:
    """Extract frames from a live video stream buffer.

    Args:
        buffer: Raw binary data received from the WebSocket stream.

    Returns:
        A list of frame byte-buffers extracted from the stream.
        Each element represents a single decoded frame.

    Note:
        Currently returns a mock single-frame list.
        Real implementation will use OpenCV / FFmpeg to decode
        the incoming buffer into individual frames.
    """
    # TODO: Implement real frame extraction with OpenCV / FFmpeg
    mock_frame = b"mock_frame_data"
    return [mock_frame]


def extract_from_file(video_path: str) -> list[bytes]:
    """Extract key frames from an uploaded video file.

    Args:
        video_path: Absolute path to the video file on disk.

    Returns:
        A list of frame byte-buffers representing key frames
        sampled from the video (e.g. one per second).

    Note:
        Currently returns mock placeholder frames.
        Real implementation will use OpenCV / FFmpeg to read the
        video file and sample frames at a configurable interval.
    """
    # TODO: Implement real frame extraction with OpenCV / FFmpeg
    mock_frames = [b"mock_frame_1", b"mock_frame_2", b"mock_frame_3"]
    return mock_frames
