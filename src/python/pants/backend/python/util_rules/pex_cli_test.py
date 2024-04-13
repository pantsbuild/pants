# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

import pytest

from pants.backend.python.util_rules import pex_cli
from pants.backend.python.util_rules.pex_cli import PexCliProcess
from pants.engine.fs import DigestContents
from pants.engine.process import Process
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *pex_cli.rules(),
            QueryRule(Process, (PexCliProcess,)),
        ]
    )


def test_custom_ca_certs(tmp_path: Path, rule_runner: RuleRunner) -> None:
    certs_file = tmp_path / "certsfile"
    certs_file.write_text("Some fake cert")
    rule_runner.set_options(
        [f"--ca-certs-path={certs_file}"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    proc = rule_runner.request(
        Process,
        [PexCliProcess(subcommand=(), extra_args=("some", "--args"), description="")],
    )

    cert_index = proc.argv.index("--cert")
    assert proc.argv[cert_index + 1] == "certsfile"

    files = rule_runner.request(DigestContents, [proc.input_digest])
    chrooted_certs_file = [f for f in files if f.path == "certsfile"]
    assert len(chrooted_certs_file) == 1
    assert b"Some fake cert" == chrooted_certs_file[0].content
