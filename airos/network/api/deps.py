from __future__ import annotations

from airos.network.api.settings import api_store_dir
from airos.os.storage import FileAirOsStore


def get_store() -> FileAirOsStore:
    return FileAirOsStore(api_store_dir())
