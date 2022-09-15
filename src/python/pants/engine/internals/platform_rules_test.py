# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.core.util_rules.environments import DockerEnvironmentTarget
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.environment import EnvironmentName
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_docker_complete_env_vars() -> None:
    rule_runner = RuleRunner(
        rules=[QueryRule(CompleteEnvironmentVars, [])],
        target_types=[DockerEnvironmentTarget],
        singleton_environment=EnvironmentName("docker"),
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                _docker_environment(
                    name='docker',
                    image='centos@sha256:a1801b843b1bfaf77c501e7a6d3f709401a1e0c83863037fa3aab063a7fdb9dc',
                    platform='linux_x86_64',
                )
                """
            )
        }
    )
    rule_runner.set_options(["--environments-preview-names={'docker': '//:docker'}"])
    result = dict(rule_runner.request(CompleteEnvironmentVars, []))

    # HOSTNAME is not deterministic across machines, so we don't care about the value.
    assert "HOSTNAME" in result
    result.pop("HOSTNAME")
    assert dict(result) == {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/root",
    }
