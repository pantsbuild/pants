# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.pants_info.list_backends import (
    BackendsOptions,
    hackily_get_module_docstring,
    list_backends,
)
from pants.core.util_rules.strip_source_roots import SourceRootStrippedSources, StripSnapshotRequest
from pants.engine.fs import EMPTY_SNAPSHOT, Digest, FileContent, FilesContent, PathGlobs, Snapshot
from pants.option.global_options import GlobalOptions
from pants.testutil.engine.util import MockConsole, MockGet, create_goal_subsystem, run_rule
from pants.testutil.subsystem.util import global_subsystem_instance
from pants.util.frozendict import FrozenDict


def test_hackily_get_module_docstring() -> None:
    assert (
        hackily_get_module_docstring(
            dedent(
                '''\
                # Some copyright

                """Module docstring."""
                x = 0
                '''
            )
        )
        == "Module docstring."
    )
    assert (
        hackily_get_module_docstring(
            dedent(
                '''\
                """Module docstring.

                Multiple lines.
                Another line.

                \t\tIndentation.
                """

                x = 0
            '''
            )
        )
        == "Module docstring. Multiple lines. Another line. Indentation."
    )
    assert (
        hackily_get_module_docstring(
            dedent(
                '''\
                """Module docstring.

                End quote not on new line."""

                x = 0
                '''
            )
        )
        == "Module docstring. End quote not on new line."
    )
    assert (
        hackily_get_module_docstring(
            dedent(
                '''\
                """First module docstring."""

                """Second module docstring."""
                '''
            )
        )
        == "First module docstring."
    )
    assert (
        hackily_get_module_docstring(
            dedent(
                '''\
                def foo():
                    """Not module docstring."""
                '''
            )
        )
        is None
    )
    assert (
        hackily_get_module_docstring(
            dedent(
                """\
                '''Single quotes confuse me. You should use Docformatter and Black.'''
                """
            )
        )
        is None
    )


def test_list_backends() -> None:
    # NB: Here, we assume that the code to find all the `register.py`s is valid. Instead, the focus
    # is on us being able to correctly extract all the relevant information from those
    # `register.py` files and then to format the information.
    all_register_pys = FilesContent(
        [
            FileContent(
                "src/python/pants/backend/fortran/register.py",
                dedent(
                    '''\
                    """Support for Fortran 98."""

                    # V1 entry-point
                    def register_goals():
                        pass

                    # This naively looks like a V2 entry-point, but it's not!
                    def rules(x: int):
                        pass
                    '''
                ).encode(),
            ),
            FileContent(
                "contrib/elixir/src/python/pants/contrib/elixir/register.py",
                dedent(
                    """\
                    # V1 entry-point
                    def register_goals():
                        pass

                    # V2 entry-point
                    def rules():
                        pass
                    """
                ).encode(),
            ),
            FileContent(
                "src/python/pants/core/register.py",
                dedent(
                    '''\
                    """Core V2 rules.

                    These are always activated.
                    """

                    def rules():
                        pass
                    '''
                ).encode(),
            ),
        ]
    )
    console = MockConsole(use_colors=False)

    def mock_strip_source_root(_) -> SourceRootStrippedSources:
        return SourceRootStrippedSources(
            EMPTY_SNAPSHOT,
            FrozenDict(
                {
                    "src/python": ("pants/backend/fortran/register.py", "pants/core/register.py"),
                    "contrib/elixir/src/python": ("pants/contrib/elixir/register.py",),
                }
            ),
        )

    run_rule(
        list_backends,
        rule_args=[
            create_goal_subsystem(BackendsOptions, sep="\\n", output_file=None),
            global_subsystem_instance(GlobalOptions),
            console,
        ],
        mock_gets=[
            MockGet(product_type=Snapshot, subject_type=PathGlobs, mock=lambda _: EMPTY_SNAPSHOT),
            MockGet(
                product_type=FilesContent, subject_type=Digest, mock=lambda _: all_register_pys
            ),
            MockGet(
                product_type=SourceRootStrippedSources,
                subject_type=StripSnapshotRequest,
                mock=mock_strip_source_root,
            ),
        ],
    )
    assert console.stdout.getvalue() == dedent(
        """\

        V1 backends
        -----------

        To enable V1 backends, add the backend to `backend_packages.add` in your
        `pants.toml`, like this:

            [GLOBAL]
            backend_packages.add = ["pants.backend.python"]

        In the below list, all activated backends end with `*`.


        pants.backend.fortran    Support for Fortran 98.

        pants.contrib.elixir     <no description>


        V2 backends
        -----------

        To enable V2 backends, add the backend to `backend_packages2.add` in your
        `pants.toml`, like this:

            [GLOBAL]
            backend_packages2.add = ["pants.backend.python"]

        In the below list, all activated backends end with `*`.


        pants.contrib.elixir    <no description>

        pants.core*             Core V2 rules. These are always activated.

        """
    )
