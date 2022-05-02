# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.lint.import_linter.skip_field import SkipImportLinterField
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonRequirementsField,
    PythonSourceField,
)
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import Digest
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, Target, TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.option.option_types import BoolOption, FileOption, SkipOption, TargetListOption
from pants.util.docutil import git_url
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class ImportLinterFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipImportLinterField).value


class ImportLinter(PythonToolBase):
    options_scope = "import-linter"
    name = "Import Linter"
    help = "The Import Linter Python linter (https://import-linter.readthedocs.io/en/stable/index.html)."

    default_version = "import-linter>=1.2.7,<2.0"
    default_main = ConsoleScript("lint-imports")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.import_linter", "import-linter.lock")
    default_lockfile_path = "src/python/pants/backend/python/lint/import_linter/import-linter.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    skip = SkipOption("lint")
    config = FileOption(
        "--config",
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to a config file understood by Import Linter
            (https://import-linter.readthedocs.io/en/stable/usage.html#top-level-configuration).

            Settings this option will disable `[{cls.options_scope}].config_discovery`. Use
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
            runs (`setup.cfg`, `.import_linter`, and `pyproject.toml`).

            Use `[{cls.options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )
    _source_plugins = TargetListOption(
        "--source-plugins",
        advanced=True,
        help=softwrap(
            """
            An optional list of `python_sources` target addresses to load custom import contracts.

            TODO
            https://import-linter.readthedocs.io/en/stable/custom_contract_types.html
            """
        ),
    )

    @property
    def config_request(self) -> ConfigFilesRequest:
        # See https://import-linter.readthedocs.io/en/stable/usage.html#configuration-file-location
        # for how Import Linter discovers config files.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=[".importlinter"],
            check_content={
                "setup.cfg": b"[importlinter]",
                "pyproject.toml": b"[importlinter]",
            },
        )

    @property
    def source_plugins(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(self._source_plugins, owning_address=None)


# --------------------------------------------------------------------------------------
# Config files
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ImportLinterConfigFile:
    digest: Digest


@rule
async def setup_import_linter_config(import_linter: ImportLinter) -> ImportLinterConfigFile:
    config_files = await Get(ConfigFiles, ConfigFilesRequest, import_linter.config_request)
    return ImportLinterConfigFile(config_files.snapshot.digest)


# --------------------------------------------------------------------------------------
# Custom contracts
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ImportLinterCustomContracts:
    requirement_strings: FrozenOrderedSet[str]
    sources_digest: Digest
    source_roots: tuple[str, ...]

    def __bool__(self) -> bool:
        return self.sources_digest != EMPTY_DIGEST


@rule("Prepare [import_linter].source_plugins", level=LogLevel.DEBUG)
async def import_linter_custom_contracts(
    import_linter: ImportLinter,
) -> ImportLinterCustomContracts:
    if not import_linter.source_plugins:
        return ImportLinterCustomContracts(FrozenOrderedSet(), EMPTY_DIGEST, ())

    contract_target_addresses = await Get(
        Addresses, UnparsedAddressInputs, import_linter.source_plugins
    )
    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest(contract_target_addresses)
    )

    requirements = PexRequirements.create_from_requirement_fields(
        (
            contract_tgt[PythonRequirementsField]
            for contract_tgt in transitive_targets.closure
            if contract_tgt.has_field(PythonRequirementsField)
        ),
        constraints_strings=(),
    )

    sources = await Get(PythonSourceFiles, PythonSourceFilesRequest(transitive_targets.closure))
    return ImportLinterCustomContracts(
        requirement_strings=requirements.req_strings,
        sources_digest=sources.source_files.snapshot.digest,
        source_roots=sources.source_roots,
    )


# --------------------------------------------------------------------------------------
# Lockfile
# --------------------------------------------------------------------------------------


class ImportLinterLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = ImportLinter.options_scope


@rule
async def setup_import_linter_lockfile(
    _: ImportLinterLockfileSentinel,
    custom_contracts: ImportLinterCustomContracts,
    import_linter: ImportLinter,
    python_setup: PythonSetup,
) -> GeneratePythonLockfile:
    if not import_linter.uses_lockfile:
        return GeneratePythonLockfile.from_tool(
            import_linter, use_pex=python_setup.generate_lockfiles_with_pex
        )

    return GeneratePythonLockfile.from_tool(
        import_linter,
        import_linter.interpreter_constraints,
        extra_requirements=custom_contracts.requirement_strings,
        use_pex=python_setup.generate_lockfiles_with_pex,
    )


# --------------------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------------------


class ImportLinterExportSentinel(ExportPythonToolSentinel):
    pass


@rule
async def import_linter_export(
    _: ImportLinterExportSentinel,
    import_linter: ImportLinter,
    custom_contracts: ImportLinterCustomContracts,
) -> ExportPythonTool:
    return ExportPythonTool(
        resolve_name=import_linter.options_scope,
        pex_request=import_linter.to_pex_request(
            interpreter_constraints=import_linter.interpreter_constraints,
            extra_requirements=custom_contracts.requirement_strings,
        ),
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, ImportLinterLockfileSentinel),
        UnionRule(ExportPythonToolSentinel, ImportLinterExportSentinel),
    )
