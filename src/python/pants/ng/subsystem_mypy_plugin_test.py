# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import tempfile
import textwrap
from pathlib import Path

import mypy.api

from pants.util.contextutil import environment_as

_FOO_GOAL_SUBSYSTEM_SOURCE = textwrap.dedent("""\
    from pants.ng.goal import GoalSubsystemNg
    from pants.ng.subsystem import option

    class FooSubsystem(GoalSubsystemNg):
        options_scope = "foo"
        help = "Run foo"

        @option(default=0, help="How much to foo")
        def level(self) -> int: ...
""")


_BAR_SUBSYSTEM_SOURCE = textwrap.dedent("""\
    from pants.ng.subsystem import ContextualSubsystem, option

    class Bar(ContextualSubsystem):
        options_scope = "bar"
        help = "Options for bar."

        @option(default="A", help="how to bar")
        def how_to(self) -> str: ...

        @option(default=false, help="whether to do the bar")
        def do_it(self) -> bool: ...
""")


def _run_mypy(source: str, *, with_plugin: bool) -> tuple[str, str]:
    """Run mypy on the given source string and return stdout."""
    # SubsystemNg and its subclasses depend on various code from the
    # codebase, so we must point mypy at it.
    import pants

    pants_src = str(Path(pants.__file__).parents[1])
    plugin_path = str(Path(__file__).parent / "subsystem_mypy_plugin.py")

    with (
        tempfile.NamedTemporaryFile(suffix=".py", mode="w") as src_f,
        tempfile.NamedTemporaryFile(suffix=".ini", mode="w") as cfg_f,
    ):
        src_f.write(source)
        src_f.flush()
        cfg_f.write("[mypy]\n")
        cfg_f.flush()
        with environment_as(MYPYPATH=pants_src):
            args = [
                src_f.name,
                "--no-error-summary",
                "--no-incremental",
                f"--config-file={cfg_f.name}",
            ]
            if with_plugin:
                args.extend(["--plugin", plugin_path])
            stdout, stderr, _code = mypy.api.run(args)
    return stdout, stderr


def test_plugin_suppresses_empty_body_on_goal_subsystem() -> None:
    stdout_noplugin, stderr_noplugin = _run_mypy(_FOO_GOAL_SUBSYSTEM_SOURCE, with_plugin=False)
    assert "empty-body" in stdout_noplugin, (
        f"Expected [empty-body] error without plugin:\n{stdout_noplugin} (err: {stderr_noplugin})"
    )

    stdout_plugin, stderr_plugin = _run_mypy(_FOO_GOAL_SUBSYSTEM_SOURCE, with_plugin=True)
    assert "empty-body" not in stdout_plugin, (
        f"Plugin did not suppress [empty-body] error:\n{stdout_plugin} (err: {stderr_plugin})"
    )


def test_plugin_suppresses_empty_body_on_contextual_subsystem() -> None:
    stdout_noplugin, stderr_noplugin = _run_mypy(_BAR_SUBSYSTEM_SOURCE, with_plugin=False)
    assert "empty-body" in stdout_noplugin, (
        f"Expected [empty-body] error without plugin:\n{stdout_noplugin} (err: {stderr_noplugin})"
    )

    stdout_plugin, stderr_plugin = _run_mypy(_BAR_SUBSYSTEM_SOURCE, with_plugin=True)
    assert "empty-body" not in stdout_plugin, (
        f"Plugin did not suppress [empty-body] error:\n{stdout_plugin} (err: {stderr_plugin})"
    )
