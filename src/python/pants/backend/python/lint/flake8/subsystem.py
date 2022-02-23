# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import cast

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.lint.flake8.skip_field import SkipFlake8Field
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
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
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    AllTargets,
    AllTargetsRequest,
    FieldSet,
    Target,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.option.custom_types import file_option, shell_str, target_option
from pants.util.docutil import bin_name, doc_url, git_url
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


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
    help = "The Flake8 Python linter (https://flake8.pycqa.org/)."

    default_version = "flake8>=3.9.2,<4.0"
    default_main = ConsoleScript("flake8")

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.flake8", "lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/python/lint/flake8/lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=f"Don't use Flake8 when running `{bin_name()} lint`",
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
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help=(
                "Path to an INI config file understood by Flake8 "
                "(https://flake8.pycqa.org/en/latest/user/configuration.html).\n\n"
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
                "runs (`.flake8`, `flake8`, `setup.cfg`, and `tox.ini`)."
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
                "An optional list of `python_sources` target addresses to load first-party "
                "plugins.\n\nYou must set the plugin's parent directory as a source root. For "
                "example, if your plugin is at `build-support/flake8/custom_plugin.py`, add "
                "'build-support/flake8' to `[source].root_patterns` in `pants.toml`. This is "
                "necessary for Pants to know how to tell Flake8 to discover your plugin. See "
                f"{doc_url('source-roots')}\n\nYou must also set `[flake8:local-plugins]` in "
                "your Flake8 config file. "
                "For example:\n\n"
                "```\n"
                "[flake8:local-plugins]\n"
                "    extension =\n"
                "        CUSTOMCODE = custom_plugin:MyChecker\n"
                "```\n\n"
                "While your plugin's code can depend on other first-party code and third-party "
                "requirements, all first-party dependencies of the plugin must live in the same "
                "directory or a subdirectory.\n\n"
                "To instead load third-party plugins, set the option "
                "`[flake8].extra_requirements`.\n\n"
                "Tip: it's often helpful to define a dedicated 'resolve' via "
                "`[python].resolves` for your Flake8 plugins such as 'flake8-plugins' "
                "so that the third-party requirements used by your plugin, like `flake8`, do not "
                "mix with the rest of your project. Read that option's help message for more info "
                "on resolves."
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

    @property
    def config_request(self) -> ConfigFilesRequest:
        # See https://flake8.pycqa.org/en/latest/user/configuration.html#configuration-locations
        # for how Flake8 discovers config files.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=cast(bool, self.options.config_discovery),
            check_existence=["flake8", ".flake8"],
            check_content={"setup.cfg": b"[flake8]", "tox.ini": b"[flake8]"},
        )

    @property
    def source_plugins(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(self.options.source_plugins, owning_address=None)


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
# Lockfile
# --------------------------------------------------------------------------------------


class Flake8LockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = Flake8.options_scope


@rule(
    desc=(
        "Determine all Python interpreter versions used by Flake8 in your project (for lockfile "
        "usage)"
    ),
    level=LogLevel.DEBUG,
)
async def setup_flake8_lockfile(
    _: Flake8LockfileSentinel,
    first_party_plugins: Flake8FirstPartyPlugins,
    flake8: Flake8,
    python_setup: PythonSetup,
) -> GeneratePythonLockfile:
    if not flake8.uses_lockfile:
        return GeneratePythonLockfile.from_tool(flake8)

    # While Flake8 will run in partitions, we need a single lockfile that works with every
    # partition.
    #
    # This ORs all unique interpreter constraints. The net effect is that every possible Python
    # interpreter used will be covered.
    all_tgts = await Get(AllTargets, AllTargetsRequest())
    relevant_targets = tuple(tgt for tgt in all_tgts if Flake8FieldSet.is_applicable(tgt))
    unique_constraints = set()
    for tgt in relevant_targets:
        if tgt.has_field(InterpreterConstraintsField):
            constraints_field = tgt[InterpreterConstraintsField]
            unique_constraints.add(
                InterpreterConstraints.create_from_compatibility_fields(
                    (constraints_field, *first_party_plugins.interpreter_constraints_fields),
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
        flake8,
        constraints or InterpreterConstraints(python_setup.interpreter_constraints),
        extra_requirements=first_party_plugins.requirement_strings,
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        *python_sources.rules(),
        UnionRule(GenerateToolLockfileSentinel, Flake8LockfileSentinel),
    )
