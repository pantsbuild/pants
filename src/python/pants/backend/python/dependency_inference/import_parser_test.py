# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from textwrap import dedent

import pytest

from pants.backend.python.dependency_inference.import_parser import find_python_imports


def test_normal_imports() -> None:
    imports = find_python_imports(
        dedent(
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
        ),
        module_name="project.app",
    )
    assert set(imports.explicit_imports) == {
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
    }
    assert not imports.inferred_imports


def test_relative_imports() -> None:
    imports = find_python_imports(
        dedent(
            """\
            from . import sibling
            from .subdir.child import Child
            from ..parent import Parent
            """
        ),
        module_name="project.util.test_utils",
    )
    assert set(imports.explicit_imports) == {
        "project.util.sibling",
        "project.util.subdir.child.Child",
        "project.parent.Parent",
    }
    assert not imports.inferred_imports


def test_imports_from_strings() -> None:
    imports = find_python_imports(
        dedent(
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
        ),
        module_name="project.app",
    )
    assert not imports.explicit_imports
    assert set(imports.inferred_imports) == {
        "a.b.d",
        "a.b2.d",
        "a.b.c.Foo",
        "a.b.c.d.Foo",
        "a.b.c.d.FooBar",
        "a.b.c.d.e.f.g.Baz",
        "a.b_c.d._bar",
        "a.b2.c.D",
    }


def test_gracefully_handle_syntax_errors() -> None:
    imports = find_python_imports("x =", module_name="project.app")
    assert not imports.explicit_imports
    assert not imports.inferred_imports


def test_works_with_python2() -> None:
    imports = find_python_imports(
        dedent(
            """\
            print "Python 2 lives on."

            import demo
            from project.demo import Demo

            importlib.import_module(b"dep.from.bytes")
            importlib.import_module(u"dep.from.str")
            """
        ),
        module_name="project.app",
    )
    assert set(imports.explicit_imports) == {"demo", "project.demo.Demo"}
    assert set(imports.inferred_imports) == {"dep.from.bytes", "dep.from.str"}


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 8),
    reason="Cannot parse Python 3.8 unless Pants is run with Python 3.8.",
)
def test_works_with_python38() -> None:
    imports = find_python_imports(
        dedent(
            """\
            is_py38 = True
            if walrus := is_py38:
                print(walrus)

            import demo
            from project.demo import Demo

            importlib.import_module("dep.from.str")
            """
        ),
        module_name="project.app",
    )
    assert set(imports.explicit_imports) == {"demo", "project.demo.Demo"}
    assert set(imports.inferred_imports) == {"dep.from.str"}
