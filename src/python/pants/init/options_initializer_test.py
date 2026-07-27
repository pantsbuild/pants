# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.base.exceptions import BuildConfigurationError
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.unions import UnionMembership
from pants.init.options_initializer import OptionsInitializer
from pants.option.errors import OptionsError
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil import rule_runner


def _initializer(
    *args: str,
) -> tuple[OptionsBootstrapper, CompleteEnvironmentVars, OptionsInitializer]:
    ob = OptionsBootstrapper.create(
        args=["--backend-packages=[]", *args], env={}, allow_pantsrc=False
    )
    env = CompleteEnvironmentVars({})
    return ob, env, OptionsInitializer(ob, rule_runner.EXECUTOR)


@pytest.mark.parametrize(
    "invalid_args, message",
    [
        (["--pants-version=99.99.9999"], "Version mismatch"),
        (
            ["--no-watch-filesystem", "--loop"],
            "The `--no-watch-filesystem` option may not be set if `--pantsd` or `--loop` is set.",
        ),
    ],
)
def test_build_config_validates_options_when_resolving_plugins(
    invalid_args: list[str], message: str
) -> None:
    # With plugins configured, `build_config` resolves them through the bootstrap scheduler, which
    # validates options as a side effect and reports failures as an `ExecutionError`.
    ob, env, initializer = _initializer("--plugins=fake-plugin", *invalid_args)
    with pytest.raises(ExecutionError) as exc:
        initializer.build_config(ob, env)
    assert message in str(exc.value)


@pytest.mark.parametrize(
    "invalid_args, native_exception, message",
    [
        (["--pants-version=99.99.9999"], BuildConfigurationError, "Version mismatch"),
        (
            ["--no-watch-filesystem", "--loop"],
            OptionsError,
            "The `--no-watch-filesystem` option may not be set if `--pantsd` or `--loop` is set.",
        ),
    ],
)
def test_options_validates_when_no_plugins_to_resolve(
    invalid_args: list[str], native_exception: type[Exception], message: str
) -> None:
    # With nothing to resolve, plugin resolution short-circuits and `build_config` does no
    # validation; the failure surfaces natively when full options are parsed.
    ob, env, initializer = _initializer(*invalid_args)
    build_config = initializer.build_config(ob, env)
    union_membership = UnionMembership.from_rules(build_config.union_rules)
    with pytest.raises(native_exception) as exc:
        initializer.options(ob, env, build_config, union_membership, raise_=True)
    assert message in str(exc.value)
