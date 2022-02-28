from typing import cast

import itertools
from pants.util.logging import LogLevel
from pants.backend.python.goals.lockfile import PythonLockfileRequest, PythonToolLockfileSentinel
from pants.backend.python.target_types import ConsoleScript
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules.pex import (
    Pex,
    PexRequest,
    PexRequirements,
)
from pants.engine.target import AllTargets, AllTargetsRequest, FieldSet, Target
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.option.custom_types import file_option, shell_str
from pants.engine.rules import Get, MultiGet, collect_rules, rule

from dataclasses import dataclass
from pants.backend.python.target_types import (
    PythonSourceField,
    InterpreterConstraintsField
)
from pants.engine.target import FieldSet, Target


@dataclass(frozen=True)
class ImportLintercheckFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    sources: PythonSourceField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(ImportLintercheckFieldSet).value

class ImportLinter(PythonToolBase):
    options_scope = "import-linter"
    help = ""

    default_version = "import-linter==1.2.6"
    default_extra_requirements = ["setuptools"]
    default_main = ConsoleScript("lint-imports")

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help="Configuration file for import-linter",
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to Flake8, e.g. "
                f'`--{cls.options_scope}-args="--ignore E123,W456 --enable-extensions H111"`'
            ),
        )
    
    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> tuple[str, ...]:
        return tuple(self.options.args)

    @property
    def config(self) -> str:
        return cast("str | None", self.options.config)

    @property
    def config_request(self) -> ConfigFilesRequest:
        # See https://flake8.pycqa.org/en/latest/user/configuration.html#configuration-locations
        # for how Flake8 discovers config files.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=".importlinter",
            discovery=cast(bool, True),
            check_existence=[".importlinter"],
        )


class ImportLinter8LockfileSentinel(PythonToolLockfileSentinel):
    options_scope = ImportLinter.options_scope

@rule(
    desc=(
        "Determine all Python interpreter versions used by Flake8 in your project (for lockfile "
        "usage)"
    ),
    level=LogLevel.DEBUG,
)
async def setup_flake8_lockfile(
    _: ImportLinter8LockfileSentinel, import_linter: ImportLinter, python_setup: PythonSetup
) -> PythonLockfileRequest:
    if not import_linter.uses_lockfile:
        return PythonLockfileRequest.from_tool(import_linter)

    # While Flake8 will run in partitions, we need a single lockfile that works with every
    # partition.
    #
    # This ORs all unique interpreter constraints. The net effect is that every possible Python
    # interpreter used will be covered.
    all_tgts = await Get(AllTargets, AllTargetsRequest())
    unique_constraints = {
        InterpreterConstraints.create_from_targets([tgt], python_setup)
        for tgt in all_tgts
        if ImportLintercheckFieldSet.is_applicable(tgt)
    }
    constraints = InterpreterConstraints(itertools.chain.from_iterable(unique_constraints))
    return PythonLockfileRequest.from_tool(
        import_linter, constraints or InterpreterConstraints(python_setup.interpreter_constraints)
    )
