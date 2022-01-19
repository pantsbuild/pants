# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.dependency_inference import parse_python_imports
from pants.backend.python.dependency_inference.parse_python_imports import (
    ParsedPythonImportInfo as ImpInfo,
)
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
    expected: dict[str, ImpInfo],
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

        try:
            import maybe_exists1
        except ImportError:
            import should_exist1


        """
    )
    assert_imports_parsed(
        rule_runner,
        content,
        expected={
            "__future__.print_function": ImpInfo(lineno=1, weak=False),
            "os": ImpInfo(lineno=3, weak=False),
            "os.path": ImpInfo(lineno=5, weak=False),
            "typing.TYPE_CHECKING": ImpInfo(lineno=6, weak=False),
            "requests": ImpInfo(lineno=8, weak=False),
            "demo": ImpInfo(lineno=10, weak=False),
            "project.demo.Demo": ImpInfo(lineno=11, weak=False),
            "project.demo.OriginalName": ImpInfo(lineno=12, weak=False),
            "multiline_import1.not_ignored1": ImpInfo(lineno=16, weak=False),
            "multiline_import1.not_ignored2": ImpInfo(lineno=23, weak=False),
            "multiline_import2.not_ignored": ImpInfo(lineno=26, weak=False),
            "project.circular_dep.CircularDep": ImpInfo(lineno=29, weak=False),
            "subprocess": ImpInfo(lineno=32, weak=True),
            "subprocess23": ImpInfo(lineno=34, weak=False),
            "pkg_resources": ImpInfo(lineno=36, weak=False),
            "not_ignored_but_looks_like_it_could_be": ImpInfo(lineno=39, weak=False),
            "also_not_ignored_but_looks_like_it_could_be": ImpInfo(lineno=45, weak=False),
            "maybe_exists1": ImpInfo(lineno=49, weak=True),
            "should_exist1": ImpInfo(lineno=51, weak=False),
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
            "project.util.sibling": ImpInfo(lineno=1, weak=False),
            "project.util.sibling.Nibling": ImpInfo(lineno=2, weak=False),
            "project.util.subdir.child.Child": ImpInfo(lineno=3, weak=False),
            "project.parent.Parent": ImpInfo(lineno=4, weak=False),
            "project.parent.Parent1": ImpInfo(lineno=6, weak=False),
            "project.parent.Guardian": ImpInfo(lineno=7, weak=False),
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
        "a.b": ImpInfo(lineno=3, weak=True),
        "a.Foo": ImpInfo(lineno=4, weak=True),
        "a.b.d": ImpInfo(lineno=5, weak=True),
        "a.b2.d": ImpInfo(lineno=6, weak=True),
        "a.b.c.Foo": ImpInfo(lineno=7, weak=True),
        "a.b.c.d.Foo": ImpInfo(lineno=8, weak=True),
        "a.b.c.d.FooBar": ImpInfo(lineno=9, weak=True),
        "a.b.c.d.e.f.g.Baz": ImpInfo(lineno=10, weak=True),
        "a.b_c.d._bar": ImpInfo(lineno=11, weak=True),
        "a.b2.c.D": ImpInfo(lineno=12, weak=True),
        "a.b.c_狗": ImpInfo(lineno=13, weak=True),
    }
    expected = {sym: info for sym, info in potentially_valid.items() if sym.count(".") >= min_dots}

    assert_imports_parsed(rule_runner, content, expected=expected, string_imports_min_dots=min_dots)
    assert_imports_parsed(rule_runner, content, string_imports=False, expected={})


def test_real_import_beats_string_import(rule_runner: RuleRunner) -> None:
    assert_imports_parsed(
        rule_runner,
        "import one.two.three; 'one.two.three'",
        expected={"one.two.three": ImpInfo(lineno=1, weak=False)},
    )


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
            "demo": ImpInfo(lineno=4, weak=False),
            "project.demo.Demo": ImpInfo(lineno=5, weak=False),
            "pkg_resources": ImpInfo(lineno=7, weak=False),
            "treat.as.a.regular.import.not.a.string.import": ImpInfo(lineno=8, weak=False),
            "dep.from.bytes": ImpInfo(lineno=10, weak=True),
            "dep.from.str": ImpInfo(lineno=11, weak=True),
            "dep.from.str_狗": ImpInfo(lineno=12, weak=True),
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
            "demo": ImpInfo(lineno=5, weak=False),
            "project.demo.Demo": ImpInfo(lineno=6, weak=False),
            "pkg_resources": ImpInfo(lineno=8, weak=False),
            "treat.as.a.regular.import.not.a.string.import": ImpInfo(lineno=9, weak=False),
            "dep.from.str": ImpInfo(lineno=11, weak=True),
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
            "demo": ImpInfo(lineno=7, weak=False),
            "project.demo.Demo": ImpInfo(lineno=8, weak=False),
            "pkg_resources": ImpInfo(lineno=10, weak=False),
            "treat.as.a.regular.import.not.a.string.import": ImpInfo(lineno=11, weak=False),
            "dep.from.str": ImpInfo(lineno=13, weak=True),
        },
    )
