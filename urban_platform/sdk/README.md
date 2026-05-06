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

### Advanced

- **`UrbanPlatformClient`** — `from urban_platform.sdk.client import UrbanPlatformClient`  
  Not included in `__all__` at the package root; import from `urban_platform.sdk.client`.

### Internal (do not treat as a supported external API)

- **`urban_platform.sdk.specs_helpers`** — shared spec load/sanitize; used by SDK/API internals.
- **`urban_platform.sdk.builders`** — pilot metadata types only.

See also `docs/REPO_RESTRUCTURING_PLAN.md` for repository layout context.
