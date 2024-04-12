# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import PurePath
from typing import Final

from pants.goal.migrate_call_by_name import Replacement

OLD_FUNC_NAME: Final[str] = "hello"
NEW_FUNC_NAME: Final[str] = "goodbye"

DEFAULT_REPLACEMENT: Final[Replacement] = Replacement(
    filename=PurePath("pants/foo/bar.py"),
    module="pants.foo.bar",
    line_range=(1, 3),
    col_range=(3, 4),
    current_source=ast.Call(func=ast.Name(id=OLD_FUNC_NAME), args=[], keywords=[]),
    new_source=ast.Call(func=ast.Name(id=NEW_FUNC_NAME), args=[], keywords=[]),
    additional_imports=[
        ast.ImportFrom(module="pants.engine.rules", names=[ast.alias("implicitly")], level=0),
        ast.ImportFrom(module="pants.greeting", names=[ast.alias(NEW_FUNC_NAME)], level=0),
    ],
)


def test_replacement_sanitizes_circular_imports():
    replacement = deepcopy(DEFAULT_REPLACEMENT)
    replacement.additional_imports.append(
        ast.ImportFrom(module="pants.foo.bar", names=[ast.alias("baz")], level=0)
    )

    sanitized_imports = replacement.sanitized_imports()
    assert len(sanitized_imports) == 2
    assert sanitized_imports[0].module == "pants.engine.rules"
    assert sanitized_imports[1].module == "pants.greeting"


def test_replacement_sanitize_noop():
    replacement = deepcopy(DEFAULT_REPLACEMENT)

    replacement.sanitize(names=set())
    assert str(replacement) == str(DEFAULT_REPLACEMENT)

    replacement.sanitize(names={"fake_name", "irrelevant_name"})
    assert str(replacement) == str(DEFAULT_REPLACEMENT)


def test_replacement_sanitize_noop_in_same_module():
    replacement = deepcopy(DEFAULT_REPLACEMENT)
    replacement.additional_imports = []
    replacement.sanitize(names={NEW_FUNC_NAME})

    unsanitized_replacement = deepcopy(DEFAULT_REPLACEMENT)
    unsanitized_replacement.additional_imports = []
    assert str(replacement) == str(unsanitized_replacement)


def test_replacement_sanitizes_shadowed_code():
    replacement = deepcopy(DEFAULT_REPLACEMENT)

    replacement.sanitize(names={NEW_FUNC_NAME})
    assert str(replacement) != str(DEFAULT_REPLACEMENT)
    assert isinstance(replacement.new_source.func, ast.Name)
    assert replacement.new_source.func.id == f"{NEW_FUNC_NAME}_get"
    assert replacement.additional_imports[1].module == "pants.greeting"
    assert replacement.additional_imports[1].names[0].name == f"{NEW_FUNC_NAME}"
    assert replacement.additional_imports[1].names[0].asname == f"{NEW_FUNC_NAME}_get"


def test_replacement_comments_are_flagged():
    assert not DEFAULT_REPLACEMENT.contains_comments("await Get(args)")
    assert DEFAULT_REPLACEMENT.contains_comments("# A comment")

    assert not DEFAULT_REPLACEMENT.contains_comments(
        """
        await Get(
            args
        )
        """
    )
    assert DEFAULT_REPLACEMENT.contains_comments(
        """
        await Get( # A comment in the replacement range
            args
        )
        """
    )
    assert DEFAULT_REPLACEMENT.contains_comments(
        """
        await Get(
            # A comment in the replacement range
            args)
        """
    )
    assert not DEFAULT_REPLACEMENT.contains_comments(
        """
        await Get(
            args
        )
        # A comment below the replacement range
        """
    )
