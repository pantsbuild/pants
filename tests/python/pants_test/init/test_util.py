# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager
from typing import Iterator, cast

from pants.fs.fs import safe_filename_from_path
from pants.init.util import init_workdir
from pants.option.option_value_container import OptionValueContainer
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import RuleRunner
from pants.util.contextutil import temporary_dir


@contextmanager
def physical_workdir_base(rule_runner: RuleRunner) -> Iterator[OptionValueContainer]:
    with temporary_dir(cleanup=False) as physical_workdir_base, rule_runner.pushd():
        bootstrap_options = create_options_bootstrapper(
            [f"--pants-physical-workdir-base={physical_workdir_base}"]
        ).bootstrap_options.for_global_scope()
        yield bootstrap_options


def assert_exists(path: str) -> None:
    assert os.path.exists(path) is True


def assert_symlink(path: str) -> None:
    assert os.path.islink(path) is True


def physical_workdir(pants_workdir: str, bootstrap_options: OptionValueContainer) -> str:
    if bootstrap_options.pants_physical_workdir_base:
        res = os.path.join(
            bootstrap_options.pants_physical_workdir_base,
            safe_filename_from_path(pants_workdir),
        )
        return cast(str, res)
    return pants_workdir


def test_init_workdir() -> None:
    rule_runner = RuleRunner()
    with physical_workdir_base(rule_runner) as bootstrap_options:
        # Assert pants_workdir exists
        assert_exists(rule_runner.pants_workdir)

        init_workdir(bootstrap_options)

        # Assert pants_workdir is a symlink after init_workdir above
        assert_symlink(rule_runner.pants_workdir)
        # Assert symlink target's physical dir exists
        assert_exists(os.path.join(physical_workdir(rule_runner.pants_workdir, bootstrap_options)))
