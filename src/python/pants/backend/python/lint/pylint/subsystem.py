# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os.path
from dataclasses import dataclass
from typing import Iterable, cast

from pants.backend.experimental.python.lockfile import (
    PythonLockfileRequest,
    PythonToolLockfileSentinel,
)
from pants.backend.python.lint.pylint.skip_field import SkipPylintField
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript, PythonSources
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSet,
    Target,
    UnexpandedTargets,
)
from pants.engine.unions import UnionRule
from pants.option.custom_types import file_option, shell_str, target_option
from pants.python.python_setup import PythonSetup
from pants.util.docutil import doc_url, git_url
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PylintFieldSet(FieldSet):
    required_fields = (PythonSources,)

    sources: PythonSources
    dependencies: Dependencies

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipPylintField).value


class Pylint(PythonToolBase):
    options_scope = "pylint"
    help = "The Pylint linter for Python code (https://www.pylint.org/)."

    default_version = "pylint>=2.6.2,<2.7"
    default_main = ConsoleScript("pylint")

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.pylint", "lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/python/lint/pylint/lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=f"Don't use Pylint when running `{register.bootstrap.pants_bin_name} lint`",
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to Pylint, e.g. "
                f'`--{cls.options_scope}-args="--ignore=foo.py,bar.py --disable=C0330,W0311"`'
            ),
        )
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help=(
                "Path to a config file understood by Pylint "
                "(http://pylint.pycqa.org/en/latest/user_guide/run.html#command-line-options).\n\n"
                f"Setting this option will disable `[{cls.options_scope}].config_discovery`. Use "
                f"this option if the config is located in a non-standard location."
            ),
        )
        register(
            "--config-discovery",
            type=bool,
            default=True,
            advanced=True,
            help=(
                "If true, Pants will include any relevant config files during "
                "runs (`.pylintrc`, `pylintrc`, `pyproject.toml`, and `setup.cfg`)."
                f"\n\nUse `[{cls.options_scope}].config` instead if your config is in a "
                f"non-standard location."
            ),
        )
        register(
            "--source-plugins",
            type=list,
            member_type=target_option,
            advanced=True,
            help=(
                "An optional list of `python_library` target addresses to load first-party "
                "plugins.\n\nYou must set the plugin's parent directory as a source root. For "
                "example, if your plugin is at `build-support/pylint/custom_plugin.py`, add "
                "'build-support/pylint' to `[source].root_patterns` in `pants.toml`. This is "
                "necessary for Pants to know how to tell Pylint to discover your plugin. See "
                f"{doc_url('source-roots')}\n\nYou must also set `load-plugins=$module_name` in "
                "your Pylint config file, and set the `[pylint].config` option in `pants.toml`."
                "\n\nWhile your plugin's code can depend on other first-party code and third-party "
                "requirements, all first-party dependencies of the plugin must live in the same "
                "directory or a subdirectory.\n\nTo instead load third-party plugins, set the "
                "option `[pylint].extra_requirements` and set the `load-plugins` option in your "
                "Pylint config."
            ),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> tuple[str, ...]:
        return tuple(self.options.args)

    @property
    def config(self) -> str | None:
        return cast("str | None", self.options.config)

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # Refer to http://pylint.pycqa.org/en/latest/user_guide/run.html#command-line-options for
        # how config files are discovered.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=cast(bool, self.options.config_discovery),
            check_existence=[".pylinrc", *(os.path.join(d, "pylintrc") for d in ("", *dirs))],
            check_content={"pyproject.toml": b"[tool.pylint]", "setup.cfg": b"[pylint."},
        )

    @property
    def source_plugins(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(self.options.source_plugins, owning_address=None)


class PylintLockfileSentinel:
    pass


@rule(
    desc=(
        "Determine all Python interpreter versions used by Pylint in your project (for "
        "lockfile usage)"
    ),
    level=LogLevel.DEBUG,
)
async def setup_pylint_lockfile(
    _: PylintLockfileSentinel, pylint: Pylint, python_setup: PythonSetup
) -> PythonLockfileRequest:
    # While Pylint will run in partitions, we need a single lockfile that works with every
    # partition.
    #
    # This first computes the constraints for each individual target, including its direct
    # dependencies (which will AND across each target in the closure). Then, it ORs all unique
    # resulting interpreter constraints. The net effect is that every possible Python interpreter
    # used will be covered.
    all_build_targets = await Get(UnexpandedTargets, AddressSpecs([DescendantAddresses("")]))
    relevant_targets = tuple(tgt for tgt in all_build_targets if PylintFieldSet.is_applicable(tgt))
    direct_deps_per_target = await MultiGet(
        Get(UnexpandedTargets, DependenciesRequest(tgt.get(Dependencies)))
        for tgt in relevant_targets
    )
    unique_constraints = {
        InterpreterConstraints.create_from_targets([tgt, *direct_deps], python_setup)
        for tgt, direct_deps in zip(relevant_targets, direct_deps_per_target)
    }
    constraints = InterpreterConstraints(itertools.chain.from_iterable(unique_constraints))
    return PythonLockfileRequest.from_tool(
        pylint, constraints or InterpreterConstraints(python_setup.interpreter_constraints)
    )


def rules():
    return (*collect_rules(), UnionRule(PythonToolLockfileSentinel, PylintLockfileSentinel))
