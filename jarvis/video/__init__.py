"""Video Understanding - M25.

Temporal video understanding built on Vision Intelligence (M23) and
Audio Intelligence (M24).
"""

from .intelligence import (
    VideoFrameResult,
    VideoEvent,
    VideoResult,
    VideoUnderstanding,
    get_video_understanding,
)

__all__ = [
    "VideoFrameResult",
    "VideoEvent",
    "VideoResult",
    "VideoUnderstanding",
    "get_video_understanding",
]
