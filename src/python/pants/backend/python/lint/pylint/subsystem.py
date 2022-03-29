# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.lint.pylint.skip_field import SkipPylintField
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonRequirementsField,
    PythonSourceField,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFilesRequest,
    StrippedPythonSourceFiles,
)
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    AllTargets,
    AllTargetsRequest,
    Dependencies,
    DependenciesRequest,
    FieldSet,
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.option.option_types import (
    ArgsListOption,
    BoolOption,
    FileOption,
    SkipOption,
    TargetListOption,
)
from pants.util.docutil import doc_url, git_url
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


@dataclass(frozen=True)
class PylintFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    dependencies: Dependencies

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipPylintField).value


# --------------------------------------------------------------------------------------
# Subsystem
# --------------------------------------------------------------------------------------


class Pylint(PythonToolBase):
    options_scope = "pylint"
    name = "Pylint"
    help = "The Pylint linter for Python code (https://www.pylint.org/)."

    default_version = "pylint>=2.11.0,<2.12"
    default_main = ConsoleScript("pylint")

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.pylint", "pylint.lock")
    default_lockfile_path = "src/python/pants/backend/python/lint/pylint/pylint.lock"
    default_lockfile_url = git_url(default_lockfile_path)
    uses_requirements_from_source_plugins = True

    skip = SkipOption("lint")
    args = ArgsListOption(example="--ignore=foo.py,bar.py --disable=C0330,W0311")
    config = FileOption(
        "--config",
        default=None,
        advanced=True,
        help=lambda cls: (
            "Path to a config file understood by Pylint "
            "(http://pylint.pycqa.org/en/latest/user_guide/run.html#command-line-options).\n\n"
            f"Setting this option will disable `[{cls.options_scope}].config_discovery`. Use "
            f"this option if the config is located in a non-standard location."
        ),
    )
    config_discovery = BoolOption(
        "--config-discovery",
        default=True,
        advanced=True,
        help=lambda cls: (
            "If true, Pants will include any relevant config files during "
            "runs (`.pylintrc`, `pylintrc`, `pyproject.toml`, and `setup.cfg`)."
            f"\n\nUse `[{cls.options_scope}].config` instead if your config is in a "
            f"non-standard location."
        ),
    )
    _source_plugins = TargetListOption(
        "--source-plugins",
        advanced=True,
        help=(
            "An optional list of `python_sources` target addresses to load first-party "
            "plugins.\n\nYou must set the plugin's parent directory as a source root. For "
            "example, if your plugin is at `build-support/pylint/custom_plugin.py`, add "
            "'build-support/pylint' to `[source].root_patterns` in `pants.toml`. This is "
            "necessary for Pants to know how to tell Pylint to discover your plugin. See "
            f"{doc_url('source-roots')}\n\n"
            f"You must also set `load-plugins=$module_name` in your Pylint config file.\n\n"
            "While your plugin's code can depend on other first-party code and third-party "
            "requirements, all first-party dependencies of the plugin must live in the same "
            "directory or a subdirectory.\n\n"
            "To instead load third-party plugins, set the "
            "option `[pylint].extra_requirements` and set the `load-plugins` option in your "
            "Pylint config.\n\n"
            "Tip: it's often helpful to define a dedicated 'resolve' via "
            "`[python].resolves` for your Pylint plugins such as 'pylint-plugins' "
            "so that the third-party requirements used by your plugin, like `pylint`, do not "
            "mix with the rest of your project. Read that option's help message for more info "
            "on resolves."
        ),
    )

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # Refer to http://pylint.pycqa.org/en/latest/user_guide/run.html#command-line-options for
        # how config files are discovered.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=[".pylintrc", *(os.path.join(d, "pylintrc") for d in ("", *dirs))],
            check_content={"pyproject.toml": b"[tool.pylint.", "setup.cfg": b"[pylint."},
        )

    @property
    def source_plugins(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(self._source_plugins, owning_address=None)


# --------------------------------------------------------------------------------------
# First-party plugins
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PylintFirstPartyPlugins:
    requirement_strings: FrozenOrderedSet[str]
    interpreter_constraints_fields: FrozenOrderedSet[InterpreterConstraintsField]
    sources_digest: Digest

    PREFIX = "__plugins"

    def __bool__(self) -> bool:
        return self.sources_digest != EMPTY_DIGEST


@rule("Prepare [pylint].source_plugins", level=LogLevel.DEBUG)
async def pylint_first_party_plugins(pylint: Pylint) -> PylintFirstPartyPlugins:
    if not pylint.source_plugins:
        return PylintFirstPartyPlugins(FrozenOrderedSet(), FrozenOrderedSet(), EMPTY_DIGEST)

    plugin_target_addresses = await Get(Addresses, UnparsedAddressInputs, pylint.source_plugins)
    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest(plugin_target_addresses)
    )

    requirements_fields: OrderedSet[PythonRequirementsField] = OrderedSet()
    interpreter_constraints_fields: OrderedSet[InterpreterConstraintsField] = OrderedSet()
    for tgt in transitive_targets.closure:
        if tgt.has_field(PythonRequirementsField):
            requirements_fields.add(tgt[PythonRequirementsField])
        if tgt.has_field(InterpreterConstraintsField):
            interpreter_constraints_fields.add(tgt[InterpreterConstraintsField])

    # NB: Pylint source plugins must be explicitly loaded via PYTHONPATH (i.e. PEX_EXTRA_SYS_PATH).
    # The value must point to the plugin's directory, rather than to a parent's directory, because
    # `load-plugins` takes a module name rather than a path to the module; i.e. `plugin`, but
    # not `path.to.plugin`. (This means users must have specified the parent directory as a
    # source root.)
    stripped_sources = await Get(
        StrippedPythonSourceFiles, PythonSourceFilesRequest(transitive_targets.closure)
    )
    prefixed_sources = await Get(
        Digest,
        AddPrefix(
            stripped_sources.stripped_source_files.snapshot.digest, PylintFirstPartyPlugins.PREFIX
        ),
    )

    return PylintFirstPartyPlugins(
        requirement_strings=PexRequirements.create_from_requirement_fields(
            requirements_fields,
            constraints_strings=(),
        ).req_strings,
        interpreter_constraints_fields=FrozenOrderedSet(interpreter_constraints_fields),
        sources_digest=prefixed_sources,
    )


# --------------------------------------------------------------------------------------
# Lockfile
# --------------------------------------------------------------------------------------


class PylintLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = Pylint.options_scope


@rule(
    desc=(
        "Determine all Python interpreter versions used by Pylint in your project (for "
        "lockfile usage)"
    ),
    level=LogLevel.DEBUG,
)
async def setup_pylint_lockfile(
    _: PylintLockfileSentinel,
    first_party_plugins: PylintFirstPartyPlugins,
    pylint: Pylint,
    python_setup: PythonSetup,
) -> GeneratePythonLockfile:
    if not pylint.uses_lockfile:
        return GeneratePythonLockfile.from_tool(
            pylint, use_pex=python_setup.generate_lockfiles_with_pex
        )

    # While Pylint will run in partitions, we need a single lockfile that works with every
    # partition. We must also consider any 3rd-party requirements used by 1st-party plugins.
    #
    # This first computes the constraints for each individual target, including its direct
    # dependencies (which will AND across each target in the closure). Then, it ORs all unique
    # resulting interpreter constraints. The net effect is that every possible Python interpreter
    # used will be covered.
    all_tgts = await Get(AllTargets, AllTargetsRequest())
    relevant_targets = tuple(tgt for tgt in all_tgts if PylintFieldSet.is_applicable(tgt))
    direct_deps_per_target = await MultiGet(
        Get(Targets, DependenciesRequest(tgt.get(Dependencies))) for tgt in relevant_targets
    )

    unique_constraints = set()
    for tgt, direct_deps in zip(relevant_targets, direct_deps_per_target):
        constraints_fields = (
            t[InterpreterConstraintsField]
            for t in (tgt, *direct_deps)
            if t.has_field(InterpreterConstraintsField)
        )
        unique_constraints.add(
            InterpreterConstraints.create_from_compatibility_fields(
                (*constraints_fields, *first_party_plugins.interpreter_constraints_fields),
                python_setup,
            )
        )
    if not unique_constraints:
        unique_constraints.add(
            InterpreterConstraints.create_from_compatibility_fields(
                first_party_plugins.interpreter_constraints_fields,
                python_setup,
            )
        )

    constraints = InterpreterConstraints(itertools.chain.from_iterable(unique_constraints))
    return GeneratePythonLockfile.from_tool(
        pylint,
        constraints or InterpreterConstraints(python_setup.interpreter_constraints),
        extra_requirements=first_party_plugins.requirement_strings,
        use_pex=python_setup.generate_lockfiles_with_pex,
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, PylintLockfileSentinel),
    )
