from __future__ import annotations


def test_product_namespace_skeleton_imports() -> None:
    import airos                 # noqa: F401
    import airos.os              # noqa: F401
    import airos.os.core         # noqa: F401
    import airos.os.sdk          # noqa: F401
    import airos.os.studio       # noqa: F401
    import airos.os.adapters     # noqa: F401
    import airos.apps            # noqa: F401
    import airos.agents          # noqa: F401
    import airos.drivers         # noqa: F401
    import airos.network         # noqa: F401

    from airos.os.sdk.client import UrbanPlatformClient  # noqa: F401
