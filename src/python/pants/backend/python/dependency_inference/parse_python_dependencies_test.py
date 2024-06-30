# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.dependency_inference import parse_python_dependencies
from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonDependencies,
)
from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonImportInfo as ImpInfo,
)
from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsePythonDependenciesRequest,
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
            *parse_python_dependencies.rules(),
            *stripped_source_files.rules(),
            *pex.rules(),
            QueryRule(ParsedPythonDependencies, [ParsePythonDependenciesRequest]),
        ],
        target_types=[PythonSourceTarget],
    )


def assert_deps_parsed(
    rule_runner: RuleRunner,
    content: str,
    *,
    expected_imports: dict[str, ImpInfo] | None = None,
    expected_assets: list[str] | None = None,
    filename: str = "project/foo.py",
    constraints: str = ">=3.6",
    string_imports: bool = True,
    string_imports_min_dots: int = 2,
    assets: bool = True,
    assets_min_slashes: int = 1,
) -> None:
    expected_imports = expected_imports or {}
    expected_assets = expected_assets or []
    rule_runner.set_options(
        [
            f"--python-infer-string-imports={string_imports}",
            f"--python-infer-string-imports-min-dots={string_imports_min_dots}",
            f"--python-infer-assets={assets}",
            f"--python-infer-assets-min-slashes={assets_min_slashes}",
            "--python-infer-use-rust-parser",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    rule_runner.write_files(
        {
            "BUILD": f"python_source(name='t', source={repr(filename)})",
            filename: content,
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t"))
    result = rule_runner.request(
        ParsedPythonDependencies,
        [
            ParsePythonDependenciesRequest(
                tgt[PythonSourceField],
                InterpreterConstraints([constraints]),
            )
        ],
    )
    assert dict(result.imports) == expected_imports
    assert list(result.assets) == sorted(expected_assets)


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
        import pragma_ignored  # pants: no-infer-dep
        from also_pragma_ignored import doesnt_matter  # pants: no-infer-dep
        from multiline_import1 import (
            not_ignored1,
            ignored1 as alias1,  # pants: no-infer-dep
            ignored2 as \\
                alias2,  # pants: no-infer-dep
            ignored3 as
                alias3,  # pants: no-infer-dep
            not_ignored2 as alias4, ignored3,  # pants: no-infer-dep
            not_ignored3, \\
            not_ignored4
        )
        from multiline_import2 import (ignored1,  # pants: no-infer-dep
            not_ignored)

        if TYPE_CHECKING:
            from project.circular_dep import CircularDep
        """
    )
    assert_deps_parsed(
        rule_runner,
        content,
        expected_imports={
            "os": ImpInfo(lineno=3, weak=False),
            "os.path": ImpInfo(lineno=5, weak=False),
            "typing.TYPE_CHECKING": ImpInfo(lineno=6, weak=False),
            "requests": ImpInfo(lineno=8, weak=False),
            "demo": ImpInfo(lineno=10, weak=False),
            "project.demo.Demo": ImpInfo(lineno=11, weak=False),
            "project.demo.OriginalName": ImpInfo(lineno=12, weak=False),
            "multiline_import1.not_ignored1": ImpInfo(lineno=16, weak=False),
            "multiline_import1.not_ignored2": ImpInfo(lineno=22, weak=False),
            "multiline_import1.not_ignored3": ImpInfo(lineno=23, weak=False),
            "multiline_import1.not_ignored4": ImpInfo(lineno=24, weak=False),
            "multiline_import2.not_ignored": ImpInfo(lineno=27, weak=False),
            "project.circular_dep.CircularDep": ImpInfo(lineno=30, weak=False),
        },
    )


def test_dunder_import_call(rule_runner: RuleRunner) -> None:
    content = dedent(
        """\
        __import__("pkg_resources")
        __import__("dunder_import_ignored")  # pants: no-infer-dep
        __import__(  # pants: no-infer-dep
            "ignored"
        )
        __import__(
            "also_ignored"  # pants: no-infer-dep
        )
        __import__(
            "also_also_ignored"
        )  # pants: no-infer-dep
        __import__(
            "not_ignored" \\
            # pants: no-infer-dep
        )
        __import__(
            "ignored_as_well" \\
        )  # pants: no-infer-dep
        """
    )
    assert_deps_parsed(
        rule_runner,
        content,
        expected_imports={
            "pkg_resources": ImpInfo(lineno=1, weak=False),
            "not_ignored": ImpInfo(lineno=13, weak=False),
        },
    )


def test_try_except(rule_runner: RuleRunner) -> None:
    content = dedent(
        """\
        try: import strong1
        except AssertionError: pass

        try: import weak1
        except ImportError: pass

        try: import weak2
        except (AssertionError, ImportError): pass

        try: import weak3
        except [AssertionError, ImportError]: pass

        try: import weak4
        except {AssertionError, ImportError}: pass
        except ImportError: pass

        try: import weak5
        except AssertionError: pass
        except ImportError: pass

        try: import weak6
        except AssertionError: import strong2
        except ImportError: import strong3
        else: import strong4
        finally: import strong5

        try: pass
        except AssertionError:
            try: import weak7
            except ImportError: import strong6

        try: import strong7
        # This would be too complicated to try and handle
        except (lambda: ImportError)(): pass

        ImpError = ImportError
        try: import strong8
        # This would be too complicated to try and handle
        except ImpError: pass

        # At least one test with import on its own line
        try:
            import weak8
        except ImportError:
            import strong9
        """
    )
    assert_deps_parsed(
        rule_runner,
        content,
        expected_imports={
            "strong1": ImpInfo(lineno=1, weak=False),
            "weak1": ImpInfo(lineno=4, weak=True),
            "weak2": ImpInfo(lineno=7, weak=True),
            "weak3": ImpInfo(lineno=10, weak=True),
            "weak4": ImpInfo(lineno=13, weak=True),
            "weak5": ImpInfo(lineno=17, weak=True),
            "weak6": ImpInfo(lineno=21, weak=True),
            "strong2": ImpInfo(lineno=22, weak=False),
            "strong3": ImpInfo(lineno=23, weak=False),
            "strong4": ImpInfo(lineno=24, weak=False),
            "strong5": ImpInfo(lineno=25, weak=False),
            "weak7": ImpInfo(lineno=29, weak=True),
            "strong6": ImpInfo(lineno=30, weak=False),
            "strong7": ImpInfo(lineno=32, weak=False),
            "strong8": ImpInfo(lineno=37, weak=False),
            "weak8": ImpInfo(lineno=43, weak=True),
            "strong9": ImpInfo(lineno=45, weak=False),
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
    assert_deps_parsed(
        rule_runner,
        content,
        filename=f"project/util/{basename}",
        expected_imports={
            "project.util.sibling": ImpInfo(lineno=1, weak=False),
            "project.util.sibling.Nibling": ImpInfo(lineno=2, weak=False),
            "project.util.subdir.child.Child": ImpInfo(lineno=3, weak=False),
            "project.parent.Parent": ImpInfo(lineno=4, weak=False),
            "project.parent.Parent1": ImpInfo(lineno=6, weak=False),
            "project.parent.Guardian": ImpInfo(lineno=7, weak=False),
        },
    )


def test_issue_18958(rule_runner: RuleRunner) -> None:
    content = dedent(
        """\
        try:
            # uh oh
            from one import thing, other_thing
        except ImportError:
            from .one import thing, other_thing
        """
    )
    assert_deps_parsed(
        rule_runner,
        content,
        filename="a/b/c/d.py",
        expected_imports={
            "one.thing": ImpInfo(lineno=3, weak=True),
            "one.other_thing": ImpInfo(lineno=3, weak=True),
            "a.b.c.one.thing": ImpInfo(lineno=5, weak=False),
            "a.b.c.one.other_thing": ImpInfo(lineno=5, weak=False),
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

            # Invalid module names are no longer permitted
            '.',
            '..',
            'a.b.',
            '..a.b.c.d',
            'a.2b.d',
            'a..b..c',
            'a.b.c.d.2Bar',
            'a.2b.c.D',
            'a.b.c_狗.',

            # Explicitly ignored strings
            'w.x',  # pants: no-infer-dep
            'w.x.Foo',  # pants: no-infer-dep
            'w.x.y.z',  # pants: no-infer-dep
            'w.x.y.z.Foo',  # pants: no-infer-dep
            'w.x.y.z.FooBar',  # pants: no-infer-dep
            'u.v.w.x.y.z.Baz',  # pants: no-infer-dep

            # Definitely invalid strings
            'I/have/a/slash',
            'I\\\\have\\\\backslashes',
            'I have whitespace',
            '\\ttabby',
            '\\nnewliney',
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

    assert_deps_parsed(
        rule_runner,
        content,
        expected_imports=expected,
        string_imports_min_dots=min_dots,
        assets=False,
    )
    assert_deps_parsed(
        rule_runner, content, string_imports=False, expected_imports={}, assets=False
    )


def test_real_import_beats_string_import(rule_runner: RuleRunner) -> None:
    assert_deps_parsed(
        rule_runner,
        "import one.two.three; 'one.two.three'",
        expected_imports={"one.two.three": ImpInfo(lineno=1, weak=False)},
    )


def test_real_import_beats_tryexcept_import(rule_runner: RuleRunner) -> None:
    assert_deps_parsed(
        rule_runner,
        dedent(
            """\
                import one.two.three
                try: import one.two.three
                except ImportError: pass
            """
        ),
        expected_imports={"one.two.three": ImpInfo(lineno=1, weak=False)},
    )


def test_issue_17283(rule_runner: RuleRunner) -> None:
    assert_deps_parsed(
        rule_runner,
        dedent(
            """\
                import foo

                from one.two import (

                  three,

                  four,  # pants: no-infer-dep

                  five,
                )

                from bar import baz
            """
        ),
        expected_imports={
            "foo": ImpInfo(lineno=1, weak=False),
            "one.two.three": ImpInfo(lineno=5, weak=False),
            "one.two.five": ImpInfo(lineno=9, weak=False),
            "bar.baz": ImpInfo(lineno=12, weak=False),
        },
    )


def test_gracefully_handle_syntax_errors(rule_runner: RuleRunner) -> None:
    assert_deps_parsed(rule_runner, "x =", expected_imports={})


def test_handle_unicode(rule_runner: RuleRunner) -> None:
    assert_deps_parsed(rule_runner, "x = 'äbç'", expected_imports={})


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

        try: import weak1
        except ImportError: import strong1
        else: import strong2
        finally: import strong3
        """
    )
    assert_deps_parsed(
        rule_runner,
        content,
        constraints="==2.7.*",
        expected_imports={
            "demo": ImpInfo(lineno=4, weak=False),
            "project.demo.Demo": ImpInfo(lineno=5, weak=False),
            "pkg_resources": ImpInfo(lineno=7, weak=False),
            "treat.as.a.regular.import.not.a.string.import": ImpInfo(lineno=8, weak=False),
            "dep.from.bytes": ImpInfo(lineno=11, weak=True),
            "dep.from.str": ImpInfo(lineno=12, weak=True),
            "dep.from.str_狗": ImpInfo(lineno=13, weak=True),
            "weak1": ImpInfo(lineno=17, weak=True),
            "strong1": ImpInfo(lineno=18, weak=False),
            "strong2": ImpInfo(lineno=19, weak=False),
            "strong3": ImpInfo(lineno=20, weak=False),
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
    assert_deps_parsed(
        rule_runner,
        content,
        constraints=">=3.8",
        expected_imports={
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
    assert_deps_parsed(
        rule_runner,
        content,
        constraints=">=3.9",
        expected_imports={
            "demo": ImpInfo(lineno=7, weak=False),
            "project.demo.Demo": ImpInfo(lineno=8, weak=False),
            "pkg_resources": ImpInfo(lineno=10, weak=False),
            "treat.as.a.regular.import.not.a.string.import": ImpInfo(lineno=11, weak=False),
            "dep.from.str": ImpInfo(lineno=13, weak=True),
        },
        expected_assets=["/dev/null"],
    )


@pytest.mark.parametrize("min_slashes", [1, 2, 3, 4])
def test_assets(rule_runner: RuleRunner, min_slashes: int) -> None:
    content = dedent(
        """\
        modules = [
            # Potentially valid assets (depending on min_slashes).
            'data/a.json',
            'data/a.txt',
            'data/a.tar.gz',
            'data/subdir1/a.json',
            'data/subdir1/a-b.json',
            'data/subdir1/subdir2/a.json',
            'data/subdir1/subdir2/subdir3/a.json',
            '狗/狗.狗',
            'data/a.b/c.d',
            'data/extensionless',
            'a/........',

            # Looks weird, but Unix and pathlib treat repeated "/" as one slash.
            # Our parsing, however considers this as multiple slashes.
            '//foo.bar',
            '//foo/////bar.txt',

            # Probably invalid assets.
            'noslashes',

            # Definitely invalid assets.
            'I have whitespace',
            '\\ttabby\\ttabby',
            '\\n/foo.json',
            'windows\\\\style.txt',
        ]
        """
    )

    potentially_valid = {
        "data/a.json",
        "data/a.txt",
        "data/a.tar.gz",
        "data/subdir1/a.json",
        "data/subdir1/a-b.json",
        "data/subdir1/subdir2/a.json",
        "data/subdir1/subdir2/subdir3/a.json",
        "狗/狗.狗",
        "data/a.b/c.d",
        "data/extensionless",
        "a/........",
        "//foo.bar",
        "//foo/////bar.txt",
    }
    expected = [s for s in potentially_valid if s.count("/") >= min_slashes]

    assert_deps_parsed(
        rule_runner, content, expected_assets=expected, assets_min_slashes=min_slashes
    )
    assert_deps_parsed(rule_runner, content, assets=False, expected_assets=[])
