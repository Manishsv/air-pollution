from __future__ import annotations

from urban_platform.api.settings import api_store_dir
from urban_platform.storage import FileAirOsStore


def get_store() -> FileAirOsStore:
    return FileAirOsStore(api_store_dir())
