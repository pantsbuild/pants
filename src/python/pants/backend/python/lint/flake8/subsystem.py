# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from dataclasses import dataclass

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.lint.flake8.skip_field import SkipFlake8Field
from pants.backend.python.subsystems.python_tool_base import ExportToolOption, PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonRequirementsField,
    PythonSourceField,
)
from pants.backend.python.util_rules import python_sources
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFilesRequest,
    StrippedPythonSourceFiles,
)
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import AddPrefix, Digest
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.rules import Get, collect_rules, rule, rule_helper
from pants.engine.target import (
    AllTargets,
    AllTargetsRequest,
    FieldSet,
    Target,
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
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class Flake8FieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipFlake8Field).value


class Flake8(PythonToolBase):
    options_scope = "flake8"
    name = "Flake8"
    help = "The Flake8 Python linter (https://flake8.pycqa.org/)."

    default_version = "flake8>=3.9.2,<4.0"
    default_main = ConsoleScript("flake8")

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.flake8", "flake8.lock")
    default_lockfile_path = "src/python/pants/backend/python/lint/flake8/flake8.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    skip = SkipOption("lint")
    args = ArgsListOption(example="--ignore E123,W456 --enable-extensions H111")
    export = ExportToolOption()
    config = FileOption(
        "--config",
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to an INI config file understood by Flake8
            (https://flake8.pycqa.org/en/latest/user/configuration.html).

            Setting this option will disable `[{cls.options_scope}].config_discovery`. Use
            this option if the config is located in a non-standard location.
            """
        ),
    )
    config_discovery = BoolOption(
        "--config-discovery",
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include any relevant config files during
            runs (`.flake8`, `flake8`, `setup.cfg`, and `tox.ini`).

            Use `[{cls.options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )
    _source_plugins = TargetListOption(
        "--source-plugins",
        advanced=True,
        help=softwrap(
            f"""
            An optional list of `python_sources` target addresses to load first-party plugins.

            You must set the plugin's parent directory as a source root. For
            example, if your plugin is at `build-support/flake8/custom_plugin.py`, add
            'build-support/flake8' to `[source].root_patterns` in `pants.toml`. This is
            necessary for Pants to know how to tell Flake8 to discover your plugin. See
            {doc_url('source-roots')}

            You must also set `[flake8:local-plugins]` in your Flake8 config file.

            For example:

                ```
                [flake8:local-plugins]
                    extension =
                        CUSTOMCODE = custom_plugin:MyChecker
                ```

            While your plugin's code can depend on other first-party code and third-party
            requirements, all first-party dependencies of the plugin must live in the same
            directory or a subdirectory.

            To instead load third-party plugins, set the option
            `[flake8].extra_requirements`.

            Tip: it's often helpful to define a dedicated 'resolve' via
            `[python].resolves` for your Flake8 plugins such as 'flake8-plugins'
            so that the third-party requirements used by your plugin, like `flake8`, do not
            mix with the rest of your project. Read that option's help message for more info
            on resolves.
            """
        ),
    )

    @property
    def config_request(self) -> ConfigFilesRequest:
        # See https://flake8.pycqa.org/en/latest/user/configuration.html#configuration-locations
        # for how Flake8 discovers config files.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=["flake8", ".flake8"],
            check_content={"setup.cfg": b"[flake8]", "tox.ini": b"[flake8]"},
        )

    @property
    def source_plugins(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(
            self._source_plugins,
            owning_address=None,
            description_of_origin=f"the option `[{self.options_scope}].source_plugins`",
        )


# --------------------------------------------------------------------------------------
# First-party plugins
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Flake8FirstPartyPlugins:
    requirement_strings: FrozenOrderedSet[str]
    interpreter_constraints_fields: FrozenOrderedSet[InterpreterConstraintsField]
    sources_digest: Digest

    PREFIX = "__plugins"

    def __bool__(self) -> bool:
        return self.sources_digest != EMPTY_DIGEST


@rule("Prepare [flake8].source_plugins", level=LogLevel.DEBUG)
async def flake8_first_party_plugins(flake8: Flake8) -> Flake8FirstPartyPlugins:
    if not flake8.source_plugins:
        return Flake8FirstPartyPlugins(FrozenOrderedSet(), FrozenOrderedSet(), EMPTY_DIGEST)

    plugin_target_addresses = await Get(Addresses, UnparsedAddressInputs, flake8.source_plugins)
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

    # NB: Flake8 source plugins must be explicitly loaded via PYTHONPATH (i.e. PEX_EXTRA_SYS_PATH).
    # The value must point to the plugin's directory, rather than to a parent's directory, because
    # `flake8:local-plugins` values take a module name rather than a path to the module;
    # i.e. `plugin`, but not `path/to/plugin`.
    # (This means users must have specified the parent directory as a source root.)
    stripped_sources = await Get(
        StrippedPythonSourceFiles, PythonSourceFilesRequest(transitive_targets.closure)
    )
    prefixed_sources = await Get(
        Digest,
        AddPrefix(
            stripped_sources.stripped_source_files.snapshot.digest, Flake8FirstPartyPlugins.PREFIX
        ),
    )

    return Flake8FirstPartyPlugins(
        requirement_strings=PexRequirements.create_from_requirement_fields(
            requirements_fields,
            constraints_strings=(),
        ).req_strings,
        interpreter_constraints_fields=FrozenOrderedSet(interpreter_constraints_fields),
        sources_digest=prefixed_sources,
    )


# --------------------------------------------------------------------------------------
# Interpreter constraints
# --------------------------------------------------------------------------------------


@rule_helper
async def _flake8_interpreter_constraints(
    first_party_plugins: Flake8FirstPartyPlugins,
    python_setup: PythonSetup,
) -> InterpreterConstraints:
    # While Flake8 will run in partitions, we need a set of constraints that works with every
    # partition.
    #
    # This ORs all unique interpreter constraints. The net effect is that every possible Python
    # interpreter used will be covered.
    all_tgts = await Get(AllTargets, AllTargetsRequest())
    unique_constraints = {
        InterpreterConstraints.create_from_compatibility_fields(
            (
                tgt[InterpreterConstraintsField],
                *first_party_plugins.interpreter_constraints_fields,
            ),
            python_setup,
        )
        for tgt in all_tgts
        if Flake8FieldSet.is_applicable(tgt)
    }
    if not unique_constraints:
        unique_constraints.add(
            InterpreterConstraints.create_from_compatibility_fields(
                first_party_plugins.interpreter_constraints_fields,
                python_setup,
            )
        )
    constraints = InterpreterConstraints(itertools.chain.from_iterable(unique_constraints))
    return constraints or InterpreterConstraints(python_setup.interpreter_constraints)


# --------------------------------------------------------------------------------------
# Lockfile
# --------------------------------------------------------------------------------------


class Flake8LockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = Flake8.options_scope


@rule(
    desc=softwrap(
        """
        Determine all Python interpreter versions used by Flake8 in your project
        (for lockfile generation)
        """
    ),
    level=LogLevel.DEBUG,
)
async def setup_flake8_lockfile(
    _: Flake8LockfileSentinel,
    first_party_plugins: Flake8FirstPartyPlugins,
    flake8: Flake8,
    python_setup: PythonSetup,
) -> GeneratePythonLockfile:
    if not flake8.uses_custom_lockfile:
        return GeneratePythonLockfile.from_tool(
            flake8, use_pex=python_setup.generate_lockfiles_with_pex
        )

    constraints = await _flake8_interpreter_constraints(first_party_plugins, python_setup)
    return GeneratePythonLockfile.from_tool(
        flake8,
        constraints,
        extra_requirements=first_party_plugins.requirement_strings,
        use_pex=python_setup.generate_lockfiles_with_pex,
    )


# --------------------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------------------


class Flake8ExportSentinel(ExportPythonToolSentinel):
    pass


@rule(
    desc=softwrap(
        """
        Determine all Python interpreter versions used by Flake8 in your project
        (for `export` goal)
        """
    ),
    level=LogLevel.DEBUG,
)
async def flake8_export(
    _: Flake8ExportSentinel,
    flake8: Flake8,
    first_party_plugins: Flake8FirstPartyPlugins,
    python_setup: PythonSetup,
) -> ExportPythonTool:
    if not flake8.export:
        return ExportPythonTool(resolve_name=flake8.options_scope, pex_request=None)
    constraints = await _flake8_interpreter_constraints(first_party_plugins, python_setup)
    return ExportPythonTool(
        resolve_name=flake8.options_scope,
        pex_request=flake8.to_pex_request(
            interpreter_constraints=constraints,
            extra_requirements=first_party_plugins.requirement_strings,
        ),
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        *python_sources.rules(),
        UnionRule(GenerateToolLockfileSentinel, Flake8LockfileSentinel),
        UnionRule(ExportPythonToolSentinel, Flake8ExportSentinel),
    )
