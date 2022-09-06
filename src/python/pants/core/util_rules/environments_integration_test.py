# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_unrecognized_build_file_symbols_during_bootstrap() -> None:
    # Our plugin resolver must look at BUILD files to load the environment, but naively it would
    # choke on unrecognized target types and Plugin Fields from the environment targets. So,
    # we special-case the bootstrap scheduler.
    build_file = dedent(
        """\
        bad_tgt_type(name='bad')
        _local_environment(name='env', bad_field=123)
        """
    )
    with setup_tmpdir({"BUILD": build_file}) as tmpdir:
        args = [f"--environments-preview-names={{'env': '{tmpdir}:env'}}", "--plugins=ansicolors"]
        run_pants([*args, "--version"]).assert_success()
        # But then we should error after bootstrapping.
        run_pants([*args, "list", tmpdir]).assert_failure()
