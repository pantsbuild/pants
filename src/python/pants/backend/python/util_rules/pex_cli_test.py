# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

import pytest

from pants.backend.python.util_rules import pex_cli
from pants.backend.python.util_rules.pex_cli import PexCliProcess
from pants.engine.fs import DigestContents
from pants.engine.process import MultiPlatformProcess
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.contextutil import temporary_dir


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *pex_cli.rules(),
            QueryRule(MultiPlatformProcess, (PexCliProcess,)),
        ]
    )


def test_custom_ca_certs(rule_runner: RuleRunner) -> None:
    with temporary_dir() as tmpdir:
        certs_file = Path(tmpdir) / "certsfile"
        certs_file.write_text("Some fake cert")
        rule_runner.set_options(
            [f"--ca-certs-path={certs_file}"],
            env_inherit={"PATH", "PYENV_ROOT", "HOME"},
        )
        proc = rule_runner.request(
            MultiPlatformProcess,
            [PexCliProcess(argv=["some", "--args"], description="")],
        )
        assert proc.processes[0].argv[2:4] == ("--cert", "certsfile")
        files = rule_runner.request(DigestContents, [proc.processes[0].input_digest])
        chrooted_certs_file = [f for f in files if f.path == "certsfile"]
        assert len(chrooted_certs_file) == 1
        assert b"Some fake cert" == chrooted_certs_file[0].content
