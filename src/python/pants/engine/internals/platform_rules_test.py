# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

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
        {"BUILD": "_docker_environment(name='docker', image='centos:7.9.2009')"}
    )
    rule_runner.set_options(["--environments-preview-names={'docker': '//:docker'}"])
    result = rule_runner.request(CompleteEnvironmentVars, [])
    assert dict(result) == {
        "PATH": "/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOSTNAME": "a02a9770c54a",
        "LANG": "C.UTF-8",
        "GPG_KEY": "E3FF2839C048B25C084DEBE9B26995E310250568",
        "PYTHON_VERSION": "3.9.14",
        "PYTHON_PIP_VERSION": "22.0.4",
        "PYTHON_SETUPTOOLS_VERSION": "58.1.0",
        "PYTHON_GET_PIP_URL": "https://github.com/pypa/get-pip/raw/5eaac1050023df1f5c98b173b248c260023f2278/public/get-pip.py",
        "PYTHON_GET_PIP_SHA256": "5aefe6ade911d997af080b315ebcb7f882212d070465df544e1175ac2be519b4",
        "HOME": "/root",
    }
