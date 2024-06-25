# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from copy import deepcopy
from pathlib import PurePath
from typing import Final, Iterable

import libcst as cst

from pants.goal.migrate_call_by_name import Replacement, remove_unused_implicitly
from pants.util.cstutil import make_importfrom_attr as import_attr

OLD_FUNC_NAME: Final[str] = "hello"
NEW_FUNC_NAME: Final[str] = "goodbye"

IMPORT_ATTR_ENGINE: Final[cst.Attribute | cst.Name] = import_attr("pants.engine.rules")
IMPORT_ATTR_GREETING: Final[cst.Attribute | cst.Name] = import_attr("pants.greeting")

DEFAULT_REPLACEMENT: Final[Replacement] = Replacement(
    filename=PurePath("pants/foo/bar.py"),
    module="pants.foo.bar",
    current_source=cst.Call(func=cst.Name(OLD_FUNC_NAME)),
    new_source=cst.Call(func=cst.Name(NEW_FUNC_NAME)),
    additional_imports=[
        cst.ImportFrom(module=IMPORT_ATTR_ENGINE, names=[cst.ImportAlias(cst.Name("implicitly"))]),
        cst.ImportFrom(
            module=IMPORT_ATTR_GREETING, names=[cst.ImportAlias(cst.Name(NEW_FUNC_NAME))]
        ),
    ],
)


def test_replacement_sanitizes_circular_imports():
    replacement = deepcopy(DEFAULT_REPLACEMENT)
    replacement.additional_imports.append(
        cst.ImportFrom(
            module=import_attr("pants.foo.bar"), names=[cst.ImportAlias(cst.Name("baz"))]
        )
    )

    sanitized_imports = replacement.sanitized_imports()
    assert len(sanitized_imports) == 2
    assert sanitized_imports[0].module is not None
    assert sanitized_imports[0].module.deep_equals(IMPORT_ATTR_ENGINE)
    assert sanitized_imports[1].module is not None
    assert sanitized_imports[1].module.deep_equals(IMPORT_ATTR_GREETING)


def test_replacement_sanitize_noop():
    replacement = deepcopy(DEFAULT_REPLACEMENT)

    replacement.sanitize(unavailable_names=set())
    assert str(replacement) == str(DEFAULT_REPLACEMENT)

    replacement.sanitize(unavailable_names={"fake_name", "irrelevant_name"})
    assert str(replacement) == str(DEFAULT_REPLACEMENT)


def test_replacement_sanitize_noop_in_same_module():
    replacement = deepcopy(DEFAULT_REPLACEMENT)
    replacement.additional_imports = []
    replacement.sanitize(unavailable_names={NEW_FUNC_NAME})

    unsanitized_replacement = deepcopy(DEFAULT_REPLACEMENT)
    unsanitized_replacement.additional_imports = []
    assert str(replacement) == str(unsanitized_replacement)


def test_replacement_sanitizes_shadowed_code():
    replacement = deepcopy(DEFAULT_REPLACEMENT)

    replacement.sanitize(unavailable_names={NEW_FUNC_NAME})
    assert str(replacement) != str(DEFAULT_REPLACEMENT)

    assert isinstance(replacement.new_source.func, cst.Name)
    assert replacement.new_source.func.value == f"{NEW_FUNC_NAME}_get"

    imp = replacement.additional_imports[1]
    assert imp.module is not None
    assert imp.module.deep_equals(IMPORT_ATTR_GREETING)

    assert isinstance(imp.names, Iterable)
    assert imp.names[0].name.deep_equals(cst.Name(NEW_FUNC_NAME))
    assert imp.names[0].asname is not None
    assert imp.names[0].asname.deep_equals(cst.AsName(cst.Name(f"{NEW_FUNC_NAME}_get")))


def test_remove_unused_implicity_noop():
    call = cst.Call(
        func=cst.Name("do_foo"), args=[cst.Arg(cst.Call(func=cst.Name("implicitly")), star="**")]
    )
    called_func = _default_func_def()

    new_call = remove_unused_implicitly(call, called_func)
    assert new_call.deep_equals(call)


def test_remove_unused_implicity_():
    call = cst.Call(
        func=cst.Name("do_foo"), args=[cst.Arg(cst.Call(func=cst.Name("implicitly")), star="**")]
    )
    called_func = _default_func_def().with_changes(name=cst.Name("do_foo"))

    new_call = remove_unused_implicitly(call, called_func)
    assert not new_call.deep_equals(call)
    assert len(new_call.args) == 0


def _default_func_def() -> cst.FunctionDef:
    return cst.FunctionDef(
        name=cst.Name("REPLACE_ME"),
        params=cst.Parameters(),
        body=cst.IndentedBlock(body=[cst.SimpleStatementLine([cst.Pass()])]),
    ).deep_clone()
