# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.core.util_rules.external_tool import DownloadedExternalTool
from pants.engine.fs import EMPTY_DIGEST
from pants.jvm.resolve.coursier_setup import (
    COURSIER_FETCH_WRAPPER_SCRIPT,
    Coursier,
    CoursierSubsystem,
)
from pants.testutil.option_util import create_subsystem
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


def make_coursier(jvm_options: tuple[str, ...] = ()) -> Coursier:
    return Coursier(
        coursier=DownloadedExternalTool(digest=EMPTY_DIGEST, exe="cs"),
        _digest=EMPTY_DIGEST,
        repos=FrozenOrderedSet(["https://repo1.maven.org/maven2"]),
        jvm_index="",
        jvm_options=jvm_options,
        _append_only_caches=FrozenDict(),
    )


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ([], ()),
        # An explicit `-J` prefix is preserved.
        (["-J-Dhttp.proxyHost=127.0.0.1"], ("-J-Dhttp.proxyHost=127.0.0.1",)),
        # A missing `-J` prefix is added.
        (["-Dhttp.proxyHost=127.0.0.1"], ("-J-Dhttp.proxyHost=127.0.0.1",)),
        # Mixed input is normalized without ever doubling the prefix.
        (["-Dfoo=1", "-J-Dbar=2"], ("-J-Dfoo=1", "-J-Dbar=2")),
    ],
)
def test_normalized_jvm_options(given: list[str], expected: tuple[str, ...]) -> None:
    subsystem = create_subsystem(CoursierSubsystem, jvm_options=given)
    assert subsystem.normalized_jvm_options == expected


def test_args_places_jvm_options_before_subcommand() -> None:
    """Coursier only honors `-J` options that appear before its subcommand."""
    coursier = make_coursier(("-J-Dhttp.proxyHost=127.0.0.1",))
    args = coursier.args(["java-home", "--jvm", "temurin:1.17"])
    exe_index = args.index(f"{Coursier.bin_dir}/cs")
    assert args[exe_index + 1 :] == (
        "-J-Dhttp.proxyHost=127.0.0.1",
        "java-home",
        "--jvm",
        "temurin:1.17",
    )


def test_args_omits_jvm_options_when_wrapped() -> None:
    """A wrapper script consumes the Coursier exe path as `$1`.

    Inserting the JVM options here would shift the wrapper's own positional arguments, so
    the wrapper receives them via `COURSIER_FETCH_WRAPPER_SCRIPT` instead.
    """
    coursier = make_coursier(("-J-Dhttp.proxyHost=127.0.0.1",))
    args = coursier.args(["out.json"], wrapper=["/bin/bash", Coursier.fetch_wrapper_script])
    assert "-J-Dhttp.proxyHost=127.0.0.1" not in args
    # The exe path must stay the first argument the wrapper script sees.
    assert args[args.index(Coursier.fetch_wrapper_script) + 1] == f"{Coursier.bin_dir}/cs"


def test_args_unchanged_without_jvm_options() -> None:
    coursier = make_coursier()
    assert coursier.args(["java-home"]) == (
        Coursier.post_process_stderr,
        f"{Coursier.bin_dir}/cs",
        "java-home",
    )


def _render_wrapper_script(jvm_options_args: str) -> str:
    return COURSIER_FETCH_WRAPPER_SCRIPT.format(
        jvm_options_args=jvm_options_args,
        repos_args="--no-default",
        coursier_working_directory="__CWD__",
        python_path="/python",
        coursier_bin_dir="__coursier",
        mkdir="/bin/mkdir",
    )


def test_fetch_wrapper_script_places_jvm_options_before_fetch() -> None:
    script = _render_wrapper_script("-J-Dhttp.proxyHost=127.0.0.1")
    assert '"$coursier_exe" -J-Dhttp.proxyHost=127.0.0.1 fetch' in script


def test_fetch_wrapper_script_without_jvm_options_still_calls_fetch() -> None:
    script = _render_wrapper_script("")
    assert "fetch --no-default" in script
