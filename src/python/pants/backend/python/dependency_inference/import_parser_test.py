# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import List, Optional

import pytest

from pants.backend.python.dependency_inference import import_parser
from pants.backend.python.dependency_inference.import_parser import (
    ParsedPythonImports,
    ParsePythonImportsRequest,
)
from pants.backend.python.target_types import PythonLibrary, PythonSources
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexInterpreterConstraints
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
        target_types=[PythonLibrary],
    )


def assert_imports_parsed(
    rule_runner: RuleRunner,
    content: Optional[str],
    *,
    expected_explicit: List[str],
    expected_string: List[str],
    filename: str = "project/foo.py",
    constraints: str = ">=3.6",
):
    if content:
        rule_runner.create_file(filename, content)
    rule_runner.add_to_build_file("project", "python_library(sources=['**/*.py'])")
    tgt = rule_runner.get_target(Address("project"))
    imports = rule_runner.request(
        ParsedPythonImports,
        [ParsePythonImportsRequest(tgt[PythonSources], PexInterpreterConstraints([constraints]))],
    )
    assert set(imports.explicit_imports) == set(expected_explicit)
    assert set(imports.string_imports) == set(expected_string)


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
        """
    )
    # We create a second file, in addition to what `assert_imports_parsed` does, to ensure we can
    # handle multiple files belonging to the same target.
    rule_runner.create_file("project/f2.py", "import second_import")
    assert_imports_parsed(
        rule_runner,
        content,
        expected_explicit=[
            "__future__.print_function",
            "os",
            "os.path",
            "typing.TYPE_CHECKING",
            "requests",
            "demo",
            "project.demo.Demo",
            "project.demo.OriginalName",
            "project.circular_dep.CircularDep",
            "second_import",
            "subprocess",
            "subprocess23",
        ],
        expected_string=[],
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
        expected_explicit=[
            "project.util.sibling",
            "project.util.sibling.Nibling",
            "project.util.subdir.child.Child",
            "project.parent.Parent",
        ],
        expected_string=[],
    )


def test_imports_from_strings(rule_runner: RuleRunner) -> None:
    content = dedent(
        """\
        modules = [
            # Valid strings
            'a.b.d',
            'a.b2.d',
            'a.b.c.Foo',
            'a.b.c.d.Foo',
            'a.b.c.d.FooBar',
            'a.b.c.d.e.f.g.Baz',
            'a.b_c.d._bar',
            'a.b2.c.D',

            # Invalid strings
            '..a.b.c.d',
            'a.b',
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
    assert_imports_parsed(
        rule_runner,
        content,
        expected_explicit=[],
        expected_string=[
            "a.b.d",
            "a.b2.d",
            "a.b.c.Foo",
            "a.b.c.d.Foo",
            "a.b.c.d.FooBar",
            "a.b.c.d.e.f.g.Baz",
            "a.b_c.d._bar",
            "a.b2.c.D",
        ],
    )


def test_gracefully_handle_syntax_errors(rule_runner: RuleRunner) -> None:
    assert_imports_parsed(rule_runner, content="x =", expected_explicit=[], expected_string=[])


def test_handle_unicode(rule_runner: RuleRunner) -> None:
    assert_imports_parsed(
        rule_runner, content="x = 'äbç'", expected_explicit=[], expected_string=[]
    )


def test_gracefully_handle_no_sources(rule_runner: RuleRunner) -> None:
    assert_imports_parsed(rule_runner, content=None, expected_explicit=[], expected_string=[])


@skip_unless_python27_present
def test_works_with_python2(rule_runner: RuleRunner) -> None:
    content = dedent(
        """\
        print "Python 2 lives on."

        import demo
        from project.demo import Demo

        importlib.import_module(b"dep.from.bytes")
        importlib.import_module(u"dep.from.str")
        """
    )
    assert_imports_parsed(
        rule_runner,
        content,
        constraints="==2.7.*",
        expected_explicit=["demo", "project.demo.Demo"],
        expected_string=["dep.from.bytes", "dep.from.str"],
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

        importlib.import_module("dep.from.str")
        """
    )
    assert_imports_parsed(
        rule_runner,
        content,
        constraints=">=3.8",
        expected_explicit=["demo", "project.demo.Demo"],
        expected_string=["dep.from.str"],
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

        importlib.import_module("dep.from.str")
        """
    )
    assert_imports_parsed(
        rule_runner,
        content,
        constraints=">=3.9",
        expected_explicit=["demo", "project.demo.Demo"],
        expected_string=["dep.from.str"],
    )
