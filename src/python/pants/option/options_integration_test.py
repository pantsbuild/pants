# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from pathlib import Path
from textwrap import dedent

from pants.fs.fs import safe_filename_from_path
from pants.testutil.pants_integration_test import (
    ensure_daemon,
    run_pants,
    run_pants_with_workdir,
    setup_tmpdir,
)


def test_invalid_options() -> None:
    config = {
        "DEFAULT": {"some_ludicrous_thing": 123},
        "GLOBAL": {"backend_packages": ["pants.backend.python"], "invalid_global": True},
        "invalid_scope": {"foo": "bar"},
        "pytest": {"bad_option": True},
    }
    config_errors = [
        "ERROR] Invalid option 'invalid_global' under [GLOBAL]",
        "ERROR] Invalid section [invalid_scope]",
        "ERROR] Invalid option 'bad_option' under [pytest]",
    ]

    # We error on invalid CLI options before validating the config file.
    result = run_pants(["--pytest-invalid=ALL", "help"], config=config)
    result.assert_failure()
    assert "Unknown flags --invalid on scope pytest" in result.stderr
    for error in config_errors:
        assert error not in result.stderr

    result = run_pants(["help"], config=config)
    result.assert_failure()
    assert "Unknown flags" not in result.stderr
    for error in config_errors:
        assert error in result.stderr


@ensure_daemon
def test_deprecation_and_ignore_warnings(use_pantsd: bool) -> None:
    plugin = dedent(
        """\
        from pants.option.subsystem import Subsystem
        from pants.option.option_types import StrOption

        class Options(Subsystem):
            help = "Options just for a test."
            options_scope = "mock-options"

            deprecated = StrOption(
                default=None,
                help="doesn't matter",
                removal_version="999.99.9.dev0",
                removal_hint="blah",
            )

        def rules():
            return [*Options.rules()]
        """
    )
    with setup_tmpdir(
        {
            "plugins/mock_options/register.py": plugin,
            "BUILD": "files(name='t', sources=['fake'])",
        }
    ) as tmpdir:
        config = {
            "GLOBAL": {
                "pythonpath": [f"%(buildroot)s/{tmpdir}/plugins"],
                "backend_packages": ["mock_options"],
            },
            "mock-options": {"deprecated": "foo"},
        }
        unmatched_glob_warning = f"Unmatched glob from {tmpdir}:t's `sources` field"

        result = run_pants(["filedeps", f"{tmpdir}:t"], config=config, use_pantsd=use_pantsd)
        result.assert_success()
        assert unmatched_glob_warning in result.stderr
        assert (
            "DEPRECATED: option 'deprecated' in scope 'mock-options' is scheduled to be removed in version"
            + " 999.99.9.dev0."
        ) in result.stderr

        config["GLOBAL"]["ignore_warnings"] = [  # type: ignore[index]
            unmatched_glob_warning,
            "$regex$DEPRECATED: option 'de.+ted'",
        ]
        ignore_result = run_pants(["filedeps", f"{tmpdir}:t"], config=config, use_pantsd=use_pantsd)
        ignore_result.assert_success()
        assert unmatched_glob_warning not in ignore_result.stderr
        assert "DEPRECATED: option 'another_deprecated'" not in ignore_result.stderr


def test_pants_symlink_workdirs(tmp_path: Path) -> None:
    symlink_workdir = tmp_path / ".pants.d"
    physical_workdir_base = tmp_path / "workdirs"
    physical_workdir = physical_workdir_base / safe_filename_from_path(symlink_workdir.as_posix())

    pants_run = run_pants_with_workdir(
        [f"--pants-physical-workdir-base={physical_workdir_base.as_posix()}", "help"],
        workdir=symlink_workdir.as_posix(),
    )
    pants_run.assert_success()
    # Make sure symlink workdir is pointing to physical workdir
    assert Path(os.readlink(symlink_workdir.as_posix())) == physical_workdir
