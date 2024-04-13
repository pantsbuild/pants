# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import typing
from typing import get_type_hints

import pytest

from pants.util.typing import ForwardRefPatched, ForwardRefPristine, _translate_piped_types_to_union


@pytest.mark.parametrize(
    "value, union",
    [
        ("FooBar", "FooBar"),
        ("Foo[Bar]", "Foo[Bar]"),
        ("Foo | Bar", "Union[Foo, Bar]"),
        ("Foo[Bar] | Foo[Baz]", "Foo[Bar] | Foo[Baz]"),
        ("Foo[Bar | Baz]", "Foo[Bar | Baz]"),
    ],
)
def test_translate_piped_types_to_union(value: str, union: str) -> None:
    assert union == _translate_piped_types_to_union(value)


def test_get_type_hints(monkeypatch) -> None:
    class A:
        b: int | float

    monkeypatch.setattr(typing, "ForwardRef", ForwardRefPristine)
    with pytest.raises(TypeError):
        get_type_hints(A)

    monkeypatch.setattr(typing, "ForwardRef", ForwardRefPatched)
    assert get_type_hints(A)
