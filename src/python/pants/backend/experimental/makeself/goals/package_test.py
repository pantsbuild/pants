import pytest
from pants.core.goals.package import BuiltPackage
from pants.engine.addresses import Address
from pants.engine.process import ProcessResult
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants_backend_makeself import makeself, system_binaries
from pants_backend_makeself.goals import package, run
from pants_backend_makeself.goals.package import (
    BuiltMakeselfArchiveArtifact,
    MakeselfArchiveFieldSet,
)
from pants_backend_makeself.makeself import RunMakeselfArchive
from pants_backend_makeself.target_types import MakeselfArchiveTarget


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            MakeselfArchiveTarget,
        ],
        rules=[
            *makeself.rules(),
            *package.rules(),
            *run.rules(),
            *system_binaries.rules(),
            QueryRule(BuiltPackage, [MakeselfArchiveFieldSet]),
            QueryRule(ProcessResult, [RunMakeselfArchive]),
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def test_makeself_package(rule_runner: RuleRunner) -> None:
    binary_name = "archive"

    rule_runner.write_files(
        {
            "src/shell/BUILD": f"makeself_archive(name='{binary_name}', startup_script='run.sh')",
            "src/shell/run.sh": "echo test",
        }
    )
    rule_runner.chmod("src/shell/run.sh", 0o777)

    target = rule_runner.get_target(Address("src/shell", target_name=binary_name))
    field_set = MakeselfArchiveFieldSet.create(target)

    package = rule_runner.request(BuiltPackage, [field_set])

    assert len(package.artifacts) == 1, field_set
    assert isinstance(package.artifacts[0], BuiltMakeselfArchiveArtifact)
    relpath = f"src.shell/{binary_name}.run"
    assert package.artifacts[0].relpath == relpath

    result = rule_runner.request(
        ProcessResult,
        [
            RunMakeselfArchive(
                exe=relpath,
                description="Run built makeself archive",
                input_digest=package.digest,
            )
        ],
    )
    assert result.stdout == b"test\n"
