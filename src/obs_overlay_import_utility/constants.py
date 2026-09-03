"""Application constants shared by the engine and interface."""

import re


__version__ = "2.0.0"
APP_TITLE = "OBS Overlay Import Utility"
TRACKING_FILENAME = "rescale_tracking.json"

# Every tool page shows the same log terminal: one heading and one height,
# so a future tool page reuses these instead of drifting its own values.
TOOL_LOG_HEADING = "Logs"
TOOL_LOG_HEIGHT = 12

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

# Non-media local files plugins, scripts, and browser sources may reference
# beyond plain media: layouts, scripts, configs, fonts, and web assets. Kept
# separate from SUPPORTED_EXTENSIONS so the exporter's media inventory stays
# accurate while the importer can still relink these references.
PLUGIN_FILE_EXTENSIONS = frozenset(
    {
        ".cfg",
        ".conf",
        ".css",
        ".dat",
        ".db",
        ".eot",
        ".ini",
        ".js",
        ".json",
        ".lua",
        ".mjs",
        ".otf",
        ".py",
        ".sqlite",
        ".toml",
        ".ttf",
        ".txt",
        ".woff",
        ".woff2",
        ".xml",
        ".yaml",
        ".yml",
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
    r"_(?:converted|importready|updated)(?:_?\d+)?\.json$",
    re.IGNORECASE,
)
