from __future__ import annotations


def test_product_namespace_skeleton_imports() -> None:
    import urban_platform.core  # noqa: F401
    import urban_platform.sdk  # noqa: F401
    import urban_platform.studio  # noqa: F401
    import urban_platform.apps  # noqa: F401
    import urban_platform.adapters  # noqa: F401

    from urban_platform.sdk.client import UrbanPlatformClient  # noqa: F401

