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
        # This target type's backend is not loaded during plugin resolution.
        shell_sources(name='shell')

        # TODO(#7735): Once we migrate the Shell backend to use environments, add one of its
        #  plugin fields here
        local_environment(name='env')
        """
    )
    with setup_tmpdir({"BUILD": build_file}) as tmpdir:
        args = [
            "--backend-packages=pants.backend.shell",
            f"--environments-preview-names={{'env': '{tmpdir}:env'}}",
            "--plugins=ansicolors",
        ]
        run_pants([*args, "list", tmpdir]).assert_success()


def test_environment_sensitive_option_fields_exist() -> None:
    pants = run_pants(["help", "local_environment"])
    pants.assert_success()
    assert "python_bootstrap_names" in pants.stdout
    assert "python_bootstrap_search_path" in pants.stdout
