# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import pytest

from pants.backend.docker.subsystems.dockerfile_wrapper_script import translate_to_address


@pytest.mark.parametrize(
    "copy_source, putative_target_address",
    [
        ("a/b", None),
        ("a/b.c", None),
        ("a.b", None),
        ("a.pex", ":a"),
        ("a/b.pex", "a:b"),
        ("a.b/c.pex", "a/b:c"),
        ("a.b.c/d.pex", "a/b/c:d"),
        ("a.b/c/d.pex", None),
        ("a/b/c.pex", None),
        ("a.0-1/b_2.pex", "a/0-1:b_2"),
        ("a#b/c.pex", None),
    ],
)
def test_translate_to_address(copy_source, putative_target_address) -> None:
    assert translate_to_address(copy_source) == putative_target_address
