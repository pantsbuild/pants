# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
from pathlib import Path

import pytest

from pants.backend.python.util_rules import pex_cli
from pants.backend.python.util_rules.pex_cli import (
    PexCliProcess,
    PexKeyringConfigurationRequest,
    PexKeyringConfigurationResponse,
)
from pants.core.util_rules import distdir, system_binaries
from pants.engine.fs import DigestContents
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import QueryRule, rule
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *pex_cli.rules(),
            *system_binaries.rules(),
            *distdir.rules(),
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


def test_pass_global_args_to_pex_cli_subsystem(tmp_path: Path, rule_runner: RuleRunner) -> None:
    """Test that arbitrary global arguments can be passed to the pex tool process."""
    rule_runner.set_options(["--pex-cli-global-args='--foo=bar --baz --spam=eggs'"])
    proc = rule_runner.request(
        Process,
        [PexCliProcess(subcommand=(), extra_args=(), description="")],
    )
    assert "--foo=bar --baz --spam=eggs" in proc.argv


class DummyKeyringConfigRequest(PexKeyringConfigurationRequest):
    name = "test-keyring-provider"


@rule
async def setup_dummy_keyring_provider(
    _request: DummyKeyringConfigRequest,
) -> PexKeyringConfigurationResponse:
    return PexKeyringConfigurationResponse(
        credentials=FrozenDict({"a-site": ("some-user", "xyzzy")})
    )


def test_keyring_support() -> None:
    rule_runner = RuleRunner(
        rules=[
            *pex_cli.rules(),
            setup_dummy_keyring_provider,
            QueryRule(ProcessResult, (PexCliProcess,)),
            QueryRule(Process, (PexCliProcess,)),
            UnionRule(PexKeyringConfigurationRequest, DummyKeyringConfigRequest),
        ]
    )
    proc = rule_runner.request(
        Process,
        [PexCliProcess(subcommand=(), extra_args=("some", "--args"), description="")],
    )

    assert "--keyring-provider=subprocess" in proc.argv

    # Ensure that the expected username/password was written to the data file on disk.
    keyring_data_path = proc.env.get("__PANTS_KEYRING_DATA")
    assert keyring_data_path is not None
    keyring_data = Path(keyring_data_path).read_text()
    assert "pants_keyring_credentials['a-site']='some-user'\n" in keyring_data
    assert "pants_keyring_credentials['a-site:some-user']='xyzzy'\n" in keyring_data

    # Now invoke the `keyring` script to verify that it works.
    proc2 = rule_runner.request(
        ProcessResult,
        [
            PexCliProcess(
                subcommand=(),
                extra_args=(
                    "--",
                    "-c",
                    textwrap.dedent(
                        """\
                import subprocess
                import sys
                result = subprocess.run(["keyring", "get", "a-site", "some-user"])
                sys.exit(result.returncode)
                """
                    ),
                ),
                description="",
            )
        ],
    )
    assert proc2.stdout.decode().strip() == "xyzzy"
