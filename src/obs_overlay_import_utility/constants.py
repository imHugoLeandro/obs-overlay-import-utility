"""Application constants shared by the engine and interface."""

import re


__version__ = "2.0.0"
APP_TITLE = "OBS Overlay Import Utility"
TRACKING_FILENAME = "rescale_tracking.json"

SUPPORTED_EXTENSIONS = frozenset(
    {
        ".aac",
        ".aif",
        ".aiff",
        ".avi",
        ".bmp",
        ".flac",
        ".gif",
        ".htm",
        ".html",
        ".jpeg",
        ".jpg",
        ".m4a",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".ogg",
        ".opus",
        ".png",
        ".svg",
        ".tif",
        ".tiff",
        ".wav",
        ".webm",
        ".webp",
        ".wma",
    }
)

LOCAL_PATH_KEYS = frozenset(
    {
        "file",
        "filename",
        "files",
        "image_path",
        "local_file",
        "mask_path",
        "media_file",
        "path",
        "playlist",
        "sound_file",
        "texture_file",
        "value",
    }
)

REMOTE_PREFIXES = (
    "data:",
    "http://",
    "https://",
    "rtmp://",
    "rtmps://",
    "rtsp://",
)

GENERATED_JSON_RE = re.compile(
    r"_(?:converted|importready)(?:_\d+)?\.json$",
    re.IGNORECASE,
)
