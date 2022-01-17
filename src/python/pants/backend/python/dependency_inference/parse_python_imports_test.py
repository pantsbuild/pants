# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.dependency_inference import parse_python_imports
from pants.backend.python.dependency_inference.parse_python_imports import (
    ParsedPythonImports,
    ParsePythonImportsRequest,
)
from pants.backend.python.target_types import PythonSourceField, PythonSourceTarget
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.testutil.python_interpreter_selection import (
    skip_unless_python27_present,
    skip_unless_python38_present,
    skip_unless_python39_present,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *parse_python_imports.rules(),
            *stripped_source_files.rules(),
            *pex.rules(),
            QueryRule(ParsedPythonImports, [ParsePythonImportsRequest]),
        ],
        target_types=[PythonSourceTarget],
    )


def assert_imports_parsed(
    rule_runner: RuleRunner,
    content: str,
    *,
    expected: dict[str, int],
    filename: str = "project/foo.py",
    constraints: str = ">=3.6",
    string_imports: bool = True,
    string_imports_min_dots: int = 2,
) -> None:
    rule_runner.set_options([], env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    rule_runner.write_files(
        {
            "BUILD": f"python_source(name='t', source={repr(filename)})",
            filename: content,
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t"))
    imports = rule_runner.request(
        ParsedPythonImports,
        [
            ParsePythonImportsRequest(
                tgt[PythonSourceField],
                InterpreterConstraints([constraints]),
                string_imports=string_imports,
                string_imports_min_dots=string_imports_min_dots,
            )
        ],
    )
    assert dict(imports) == expected


def test_normal_imports(rule_runner: RuleRunner) -> None:
    content = dedent(
        """\
        from __future__ import print_function

        import os
        import os  # repeated to test the line number
        import os.path
        from typing import TYPE_CHECKING

        import requests

        import demo
        from project.demo import Demo
        from project.demo import OriginalName as Renamed
        import pragma_ignored  # pants: ignore
        from also_pragma_ignored import doesnt_matter  # pants: ignore
        from multiline_import1 import (
            not_ignored1,
            ignored1 as alias1,  # pants: ignore
            ignored2 as \\
                alias2,  # pants: ignore
            ignored3 as  # pants: ignore
                alias3,
            ignored4 as alias4, ignored4,  # pants: ignore
            not_ignored2,
        )
        from multiline_import2 import (ignored1,  # pants: ignore
            not_ignored)

        if TYPE_CHECKING:
            from project.circular_dep import CircularDep

        try:
            import subprocess
        except ImportError:
            import subprocess23 as subprocess

        __import__("pkg_resources")
        __import__("dunder_import_ignored")  # pants: ignore
        __import__(  # pants: ignore
            "not_ignored_but_looks_like_it_could_be"
        )
        __import__(
            "ignored"  # pants: ignore
        )
        __import__(
            "also_not_ignored_but_looks_like_it_could_be"
        )  # pants: ignore
        """
    )
    assert_imports_parsed(
        rule_runner,
        content,
        expected={
            "__future__.print_function": 1,
            "os": 3,
            "os.path": 5,
            "typing.TYPE_CHECKING": 6,
            "requests": 8,
            "demo": 10,
            "project.demo.Demo": 11,
            "project.demo.OriginalName": 12,
            "multiline_import1.not_ignored1": 16,
            "multiline_import1.not_ignored2": 23,
            "multiline_import2.not_ignored": 26,
            "project.circular_dep.CircularDep": 29,
            "subprocess": 32,
            "subprocess23": 34,
            "pkg_resources": 36,
            "not_ignored_but_looks_like_it_could_be": 39,
            "also_not_ignored_but_looks_like_it_could_be": 45,
        },
    )


@pytest.mark.parametrize("basename", ["foo.py", "__init__.py"])
def test_relative_imports(rule_runner: RuleRunner, basename: str) -> None:
    content = dedent(
        """\
        from . import sibling
        from .sibling import Nibling
        from .subdir.child import Child
        from ..parent import Parent
        from ..parent import (
            Parent1,
            Guardian as Parent2
        )
        """
    )
    assert_imports_parsed(
        rule_runner,
        content,
        filename=f"project/util/{basename}",
        expected={
            "project.util.sibling": 1,
            "project.util.sibling.Nibling": 2,
            "project.util.subdir.child.Child": 3,
            "project.parent.Parent": 4,
            "project.parent.Parent1": 6,
            "project.parent.Guardian": 7,
        },
    )


@pytest.mark.parametrize("min_dots", [1, 2, 3, 4])
def test_imports_from_strings(rule_runner: RuleRunner, min_dots: int) -> None:
    content = dedent(
        """\
        modules = [
            # Potentially valid strings (depending on min_dots).
            'a.b',
            'a.Foo',
            'a.b.d',
            'a.b2.d',
            'a.b.c.Foo',
            'a.b.c.d.Foo',
            'a.b.c.d.FooBar',
            'a.b.c.d.e.f.g.Baz',
            'a.b_c.d._bar',
            'a.b2.c.D',
            'a.b.c_狗',

            # Definitely invalid strings
            '..a.b.c.d',
            'a.B.d',
            'a.2b.d',
            'a..b..c',
            'a.b.c.d.2Bar',
            'a.b_c.D.bar',
            'a.b_c.D.Bar',
            'a.2b.c.D',
        ]

        for module in modules:
            importlib.import_module(module)
        """
    )

    potentially_valid = {
        "a.b": 3,
        "a.Foo": 4,
        "a.b.d": 5,
        "a.b2.d": 6,
        "a.b.c.Foo": 7,
        "a.b.c.d.Foo": 8,
        "a.b.c.d.FooBar": 9,
        "a.b.c.d.e.f.g.Baz": 10,
        "a.b_c.d._bar": 11,
        "a.b2.c.D": 12,
        "a.b.c_狗": 13,
    }
    expected = {sym: line for sym, line in potentially_valid.items() if sym.count(".") >= min_dots}

    assert_imports_parsed(rule_runner, content, expected=expected, string_imports_min_dots=min_dots)
    assert_imports_parsed(rule_runner, content, string_imports=False, expected={})


def test_gracefully_handle_syntax_errors(rule_runner: RuleRunner) -> None:
    assert_imports_parsed(rule_runner, "x =", expected={})


def test_handle_unicode(rule_runner: RuleRunner) -> None:
    assert_imports_parsed(rule_runner, "x = 'äbç'", expected={})


@skip_unless_python27_present
def test_works_with_python2(rule_runner: RuleRunner) -> None:
    content = dedent(
        """\
        # -*- coding: utf-8 -*-
        print "Python 2 lives on."

        import demo
        from project.demo import Demo

        __import__(u"pkg_resources")
        __import__(b"treat.as.a.regular.import.not.a.string.import")

        importlib.import_module(b"dep.from.bytes")
        importlib.import_module(u"dep.from.str")
        importlib.import_module(u"dep.from.str_狗")

        b"\\xa0 a non-utf8 string, make sure we ignore it"
        """
    )
    assert_imports_parsed(
        rule_runner,
        content,
        constraints="==2.7.*",
        expected={
            "demo": 4,
            "project.demo.Demo": 5,
            "pkg_resources": 7,
            "treat.as.a.regular.import.not.a.string.import": 8,
            "dep.from.bytes": 10,
            "dep.from.str": 11,
            "dep.from.str_狗": 12,
        },
    )


@skip_unless_python38_present
def test_works_with_python38(rule_runner: RuleRunner) -> None:
    content = dedent(
        """\
        is_py38 = True
        if walrus := is_py38:
            print(walrus)

        import demo
        from project.demo import Demo

        __import__("pkg_resources")
        __import__("treat.as.a.regular.import.not.a.string.import")

        importlib.import_module("dep.from.str")
        """
    )
    assert_imports_parsed(
        rule_runner,
        content,
        constraints=">=3.8",
        expected={
            "demo": 5,
            "project.demo.Demo": 6,
            "pkg_resources": 8,
            "treat.as.a.regular.import.not.a.string.import": 9,
            "dep.from.str": 11,
        },
    )


@skip_unless_python39_present
def test_works_with_python39(rule_runner: RuleRunner) -> None:
    content = dedent(
        """\
        # This requires the new PEG parser.
        with (
            open("/dev/null") as f,
        ):
            pass

        import demo
        from project.demo import Demo

        __import__("pkg_resources")
        __import__("treat.as.a.regular.import.not.a.string.import")

        importlib.import_module("dep.from.str")
        """
    )
    assert_imports_parsed(
        rule_runner,
        content,
        constraints=">=3.9",
        expected={
            "demo": 7,
            "project.demo.Demo": 8,
            "pkg_resources": 10,
            "treat.as.a.regular.import.not.a.string.import": 11,
            "dep.from.str": 13,
        },
    )
