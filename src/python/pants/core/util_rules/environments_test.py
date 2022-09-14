# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent

import pytest

from pants.build_graph.address import Address, ResolveError
from pants.core.util_rules import environments
from pants.core.util_rules.environments import (
    LOCAL_ENVIRONMENT_MATCHER,
    AllEnvironmentTargets,
    AmbiguousEnvironmentError,
    ChosenLocalEnvironmentName,
    DockerEnvironmentTarget,
    EnvironmentField,
    EnvironmentName,
    EnvironmentNameRequest,
    EnvironmentTarget,
    LocalEnvironmentTarget,
    NoCompatibleEnvironmentError,
    UnrecognizedEnvironmentError,
)
from pants.engine.target import FieldSet, OptionalSingleSourceField, Target
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *environments.rules(),
            QueryRule(AllEnvironmentTargets, []),
            QueryRule(EnvironmentTarget, [EnvironmentName]),
            QueryRule(EnvironmentName, [EnvironmentNameRequest]),
        ],
        target_types=[LocalEnvironmentTarget, DockerEnvironmentTarget],
        singleton_environment=None,
    )


def test_all_environments(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                _local_environment(name='e1')
                _local_environment(name='e2')
                _local_environment(name='no-name')
                _docker_environment(name='docker', image="centos6:latest")
                """
            )
        }
    )
    rule_runner.set_options(
        ["--environments-preview-names={'e1': '//:e1', 'e2': '//:e2', 'docker': '//:docker'}"]
    )
    result = rule_runner.request(AllEnvironmentTargets, [])
    assert {i: j.address for (i, j) in result.items()} == {
        "e1": Address("", target_name="e1"),
        "e2": Address("", target_name="e2"),
        "docker": Address("", target_name="docker"),
    }


def test_choose_local_environment(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                _local_environment(name='e1')
                _local_environment(name='e2')
                _local_environment(name='not-compatible', compatible_platforms=[])
                _docker_environment(name='docker', docker_image="centos6:latest")
                """
            )
        }
    )

    def get_env() -> EnvironmentTarget:
        name = rule_runner.request(ChosenLocalEnvironmentName, [])
        return rule_runner.request(EnvironmentTarget, [EnvironmentName(name.val)])

    # If `--names` is not set, do not choose an environment.
    assert get_env().val is None

    rule_runner.set_options(["--environments-preview-names={'e': '//:e1'}"])
    assert get_env().val.address == Address("", target_name="e1")  # type: ignore[union-attr]

    # Error if `--names` set, but no compatible platforms
    rule_runner.set_options(["--environments-preview-names={'e': '//:not-compatible'}"])
    with engine_error(NoCompatibleEnvironmentError):
        get_env()

    # Error if >1 compatible targets.
    rule_runner.set_options(["--environments-preview-names={'e1': '//:e1', 'e2': '//:e2'}"])
    with engine_error(AmbiguousEnvironmentError):
        get_env()


def test_resolve_environment_name(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                _local_environment(name='local')
                # Intentionally set this to no platforms so that it cannot be autodiscovered.
                _local_environment(name='hardcoded', compatible_platforms=[])
                _docker_environment(name='docker', image="centos6:latest")
                """
            )
        }
    )

    def get_name(v: str) -> EnvironmentName:
        return rule_runner.request(
            EnvironmentName, [EnvironmentNameRequest(v, description_of_origin="foo")]
        )

    # If `--names` is not set, and the local matcher is used, do not choose an environment.
    assert get_name(LOCAL_ENVIRONMENT_MATCHER).val is None
    # Else, error for unrecognized names.
    with engine_error(UnrecognizedEnvironmentError):
        get_name("hardcoded")

    rule_runner.set_options(
        [
            "--environments-preview-names={'local': '//:local', 'hardcoded': '//:hardcoded', 'docker': '//:docker'}"
        ]
    )
    assert get_name(LOCAL_ENVIRONMENT_MATCHER).val == "local"
    assert get_name("hardcoded").val == "hardcoded"
    assert get_name("docker").val == "docker"
    with engine_error(UnrecognizedEnvironmentError):
        get_name("fake")


def test_resolve_environment_tgt(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": "_local_environment(name='env')"})
    rule_runner.set_options(
        ["--environments-preview-names={'env': '//:env', 'bad-address': '//:fake'}"]
    )

    def get_tgt(v: str | None) -> EnvironmentTarget:
        return rule_runner.request(EnvironmentTarget, [EnvironmentName(v)])

    assert get_tgt(None).val is None

    # If the name is not defined, error.
    with engine_error(AssertionError):
        get_tgt("bad")

    assert get_tgt("env").val.address == Address("", target_name="env")  # type: ignore[union-attr]
    with engine_error(ResolveError):
        get_tgt("bad-address")


def test_environment_name_request_from_field_set() -> None:
    class EnvFieldSubclass(EnvironmentField):
        alias = "the_env_field"  # This intentionally uses a custom alias.

    class Tgt(Target):
        alias = "tgt"
        help = "foo"
        core_fields = (OptionalSingleSourceField, EnvFieldSubclass)

    @dataclass(frozen=True)
    class NoEnvFS(FieldSet):
        required_fields = (OptionalSingleSourceField,)

        source: OptionalSingleSourceField

    @dataclass(frozen=True)
    class EnvFS(FieldSet):
        required_fields = (OptionalSingleSourceField,)

        source: OptionalSingleSourceField
        the_env_field: EnvironmentField  # This intentionally uses an unusual attribute name.

    tgt = Tgt({EnvFieldSubclass.alias: "my_env"}, Address("dir"))
    assert EnvironmentNameRequest.from_field_set(NoEnvFS.create(tgt)) == EnvironmentNameRequest(
        LOCAL_ENVIRONMENT_MATCHER,
        description_of_origin="the `environment` field from the target dir:dir",
    )
    assert EnvironmentNameRequest.from_field_set(EnvFS.create(tgt)) == EnvironmentNameRequest(
        "my_env", description_of_origin="the `the_env_field` field from the target dir:dir"
    )
