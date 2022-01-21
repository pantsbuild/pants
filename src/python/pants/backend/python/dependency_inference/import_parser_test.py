# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.dependency_inference import import_parser
from pants.backend.python.dependency_inference.import_parser import (
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
            *import_parser.rules(),
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
    expected: list[str],
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
    assert list(imports) == sorted(expected)


def test_normal_imports(rule_runner: RuleRunner) -> None:
    content = dedent(
        """\
        from __future__ import print_function

        import os
        import os.path
        from typing import TYPE_CHECKING

        import requests

        import demo
        from project.demo import Demo
        from project.demo import OriginalName as Renamed

        if TYPE_CHECKING:
            from project.circular_dep import CircularDep

        try:
            import subprocess
        except ImportError:
            import subprocess23 as subprocess

        __import__("pkg_resources")
        """
    )
    assert_imports_parsed(
        rule_runner,
        content,
        expected=[
            "__future__.print_function",
            "os",
            "os.path",
            "typing.TYPE_CHECKING",
            "requests",
            "demo",
            "project.demo.Demo",
            "project.demo.OriginalName",
            "project.circular_dep.CircularDep",
            "subprocess",
            "subprocess23",
            "pkg_resources",
        ],
    )


@pytest.mark.parametrize("basename", ["foo.py", "__init__.py"])
def test_relative_imports(rule_runner: RuleRunner, basename: str) -> None:
    content = dedent(
        """\
        from . import sibling
        from .sibling import Nibling
        from .subdir.child import Child
        from ..parent import Parent
        """
    )
    assert_imports_parsed(
        rule_runner,
        content,
        filename=f"project/util/{basename}",
        expected=[
            "project.util.sibling",
            "project.util.sibling.Nibling",
            "project.util.subdir.child.Child",
            "project.parent.Parent",
        ],
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

    potentially_valid = [
        "a.b",
        "a.Foo",
        "a.b.d",
        "a.b2.d",
        "a.b.c.Foo",
        "a.b.c.d.Foo",
        "a.b.c.d.FooBar",
        "a.b.c.d.e.f.g.Baz",
        "a.b_c.d._bar",
        "a.b2.c.D",
        "a.b.c_狗",
    ]
    expected = [sym for sym in potentially_valid if sym.count(".") >= min_dots]

    assert_imports_parsed(rule_runner, content, expected=expected, string_imports_min_dots=min_dots)
    assert_imports_parsed(rule_runner, content, string_imports=False, expected=[])


def test_gracefully_handle_syntax_errors(rule_runner: RuleRunner) -> None:
    assert_imports_parsed(rule_runner, "x =", expected=[])


def test_handle_unicode(rule_runner: RuleRunner) -> None:
    assert_imports_parsed(rule_runner, "x = 'äbç'", expected=[])


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
        __import__(u"{}".format("interpolation"))

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
        expected=[
            "demo",
            "dep.from.bytes",
            "dep.from.str",
            "dep.from.str_狗",
            "project.demo.Demo",
            "pkg_resources",
            "treat.as.a.regular.import.not.a.string.import",
        ],
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
        expected=[
            "demo",
            "dep.from.str",
            "project.demo.Demo",
            "pkg_resources",
            "treat.as.a.regular.import.not.a.string.import",
        ],
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
        expected=[
            "demo",
            "dep.from.str",
            "project.demo.Demo",
            "pkg_resources",
            "treat.as.a.regular.import.not.a.string.import",
        ],
    )
