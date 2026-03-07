"""TrustKit AI — Metadata Analyzer Module (Deep Scan).

Extracts metadata and forensic indicators from image frames and
video files. Used to detect suspicious or outdated media in
property listings.

Uses Pillow for EXIF extraction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image  # type: ignore
from PIL.ExifTags import TAGS, GPSTAGS  # type: ignore


# ---------------------------------------------------------------------------
# Core analyzer class
# ---------------------------------------------------------------------------


class MetadataAnalyzer:
    """
    Extracts metadata and forensic indicators from image frames.
    Used to detect suspicious or outdated media in property listings.
    """

    def __init__(self) -> None:
        pass

    def analyze(self, image_path: str) -> Dict[str, Any]:
        """
        Main analysis entrypoint.

        Args:
            image_path: path to extracted frame

        Returns:
            dictionary containing metadata + suspicion flags
        """

        metadata = self._extract_exif(image_path)
        gps = self._extract_gps(metadata)

        result: Dict[str, Any] = {
            "file": image_path,
            "created_time": metadata.get("DateTimeOriginal"),
            "camera_model": metadata.get("Model"),
            "camera_make": metadata.get("Make"),
            "software": metadata.get("Software"),
            "gps": gps,
            "suspicious_flags": self._detect_suspicious(metadata),
        }

        return result

    def _extract_exif(self, image_path: str) -> Dict[str, Any]:
        """
        Extract EXIF metadata from image.
        """

        path = Path(image_path)

        if not path.exists():
            return {}

        try:
            with Image.open(path) as image:
                exif_data = image._getexif()

            if not exif_data:
                return {}

            metadata: Dict[str, Any] = {}

            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, tag_id)
                metadata[tag] = value

            return metadata

        except Exception:
            return {}

    def _extract_gps(self, metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract GPS coordinates if available.
        """

        gps_info = metadata.get("GPSInfo")

        if not gps_info:
            return None

        gps_data: Dict[str, Any] = {}

        for key in gps_info.keys():
            decoded = GPSTAGS.get(key, key)
            gps_data[decoded] = gps_info[key]

        return gps_data

    def _detect_suspicious(self, metadata: Dict[str, Any]) -> List[str]:
        """
        Detect suspicious metadata patterns.
        """

        flags: List[str] = []

        if not metadata:
            flags.append("metadata_unavailable")

        if metadata.get("Software"):
            flags.append("edited_media")

        if not metadata.get("DateTimeOriginal"):
            flags.append("missing_creation_time")

        if not metadata.get("Model"):
            flags.append("unknown_camera_source")

        return flags


# ---------------------------------------------------------------------------
# Backward-compatible convenience function
# ---------------------------------------------------------------------------
# Preserves the original module API so that the existing import in
# deep_scan.py continues to work without changes:
#   from modules.metadata_analyzer import analyze as analyze_metadata

_default_analyzer = MetadataAnalyzer()


def analyze(video_path: str) -> dict:
    """Analyze metadata of a file for forensic indicators.

    Backward-compatible wrapper around MetadataAnalyzer.

    Args:
        video_path: Absolute path to the file on disk.

    Returns:
        A dict containing forensic metadata findings.
    """
    return _default_analyzer.analyze(video_path)
