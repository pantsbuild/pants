# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath

import pytest

from pants.backend.terraform.hcl2_parser import resolve_pure_path


def test_resolve_pure_path() -> None:
    assert resolve_pure_path(PurePath("foo/bar/hello/world"), PurePath("../../grok")) == PurePath(
        "foo/bar/grok"
    )
    assert resolve_pure_path(
        PurePath("foo/bar/hello/world"), PurePath("../../../../grok")
    ) == PurePath("grok")
    with pytest.raises(ValueError):
        resolve_pure_path(PurePath("foo/bar/hello/world"), PurePath("../../../../../grok"))
    assert resolve_pure_path(PurePath("foo/bar/hello/world"), PurePath("./grok")) == PurePath(
        "foo/bar/hello/world/grok"
    )
