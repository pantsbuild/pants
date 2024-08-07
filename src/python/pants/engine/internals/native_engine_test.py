# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.engine.internals.native_engine import (
    EMPTY_DIGEST,
    InferenceMetadata,
    NativeDependenciesRequest,
)


def test_can_construct_javascript_metadata() -> None:
    InferenceMetadata.javascript(
        package_root="some/dir",
        import_patterns={"a-pattern-*": ["replaces-me-*"]},
        config_root=None,
        paths={},
    )


def test_can_construct_native_dependencies_request() -> None:
    NativeDependenciesRequest(EMPTY_DIGEST, None)
    NativeDependenciesRequest(
        EMPTY_DIGEST,
        InferenceMetadata.javascript(
            package_root="some/dir", import_patterns={}, config_root=None, paths={"src": ("1", "2")}
        ),
    )
