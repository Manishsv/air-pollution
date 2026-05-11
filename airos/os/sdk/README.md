## `urban_platform.sdk`

The AirOS Python SDK lives in this package (not a separately published wheel yet).

### Public surface (package root)

`urban_platform/sdk/__init__.py` **re-exports** helpers listed in **`__all__`**. Prefer:

```python
from urban_platform.sdk import get_app_descriptor, validate_payload
```

for symbols in that list. The authoritative contract is **`docs/SDK_SURFACE.md`**.

### Submodule imports

The same functions are available on submodules (for example `urban_platform.sdk.apps`,
`urban_platform.sdk.contracts`). CLI, API, and tests often import from submodules; both
styles are valid in-repo.

### Runtime query client

```python
from airos.os.sdk import AirOSClient

client = AirOSClient()
packets = client.get_decision_packets()
```

`AirOSClient` reads from the live store (SQLite + output files). It is included
in `__all__` and is the recommended way to access runtime data.

### Store helpers

```python
from airos.os.sdk import store

signals  = store.get_signals("bangalore")
patterns = store.get_city_patterns("bangalore")
health   = store.get_city_health_summary("bangalore")
```

### Internal (do not treat as a supported external API)

- **`airos.os.sdk.specs_helpers`** — shared spec load/sanitize; used by SDK/API internals.

See also `docs/REPO_RESTRUCTURING_PLAN.md` for repository layout context.
