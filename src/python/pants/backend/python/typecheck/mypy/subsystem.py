# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    GeneratePythonToolLockfileSentinel,
)
from pants.backend.python.subsystems.python_tool_base import ExportToolOption, PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonRequirementsField,
    PythonSourceField,
)
from pants.backend.python.typecheck.mypy.skip_field import SkipMyPyField
from pants.backend.python.util_rules import partition
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.partition import _find_all_unique_interpreter_constraints
from pants.backend.python.util_rules.pex import PexRequest
from pants.backend.python.util_rules.pex_requirements import (
    EntireLockfile,
    PexRequirements,
    ToolCustomLockfile,
)
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.generate_lockfiles import NO_TOOL_LOCKFILE, GenerateToolLockfileSentinel
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.lockfile_metadata import calculate_invalidation_digest
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import EMPTY_DIGEST, Digest, DigestContents, FileContent
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
    StrListOption,
    StrOption,
    TargetListOption,
)
from pants.util.docutil import bin_name, doc_url, git_url
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MyPyFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    sources: PythonSourceField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipMyPyField).value


# --------------------------------------------------------------------------------------
# Subsystem
# --------------------------------------------------------------------------------------


class MyPy(PythonToolBase):
    options_scope = "mypy"
    name = "MyPy"
    help = "The MyPy Python type checker (http://mypy-lang.org/)."

    default_version = "mypy==0.961"
    default_main = ConsoleScript("mypy")

    # See `mypy/rules.py`. We only use these default constraints in some situations.
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.typecheck.mypy", "mypy.lock")
    default_lockfile_path = "src/python/pants/backend/python/typecheck/mypy/mypy.lock"
    default_lockfile_url = git_url(default_lockfile_path)
    uses_requirements_from_source_plugins = True

    skip = SkipOption("check")
    args = ArgsListOption(example="--python-version 3.7 --disallow-any-expr")
    export = ExportToolOption()
    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to a config file understood by MyPy
            (https://mypy.readthedocs.io/en/stable/config_file.html).

            Setting this option will disable `[{cls.options_scope}].config_discovery`. Use
            this option if the config is located in a non-standard location.
            """
        ),
    )
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include any relevant config files during runs
            (`mypy.ini`, `.mypy.ini`, and `setup.cfg`).

            Use `[{cls.options_scope}].config` instead if your config is in a non-standard location.
            """
        ),
    )
    _source_plugins = TargetListOption(
        advanced=True,
        help=softwrap(
            """
            An optional list of `python_sources` target addresses to load first-party plugins.

            You must also set `plugins = path.to.module` in your `mypy.ini`, and
            set the `[mypy].config` option in your `pants.toml`.

            To instead load third-party plugins, set the option `[mypy].extra_requirements`
            and set the `plugins` option in `mypy.ini`.
            Tip: it's often helpful to define a dedicated 'resolve' via
            `[python].resolves` for your MyPy plugins such as 'mypy-plugins'
            so that the third-party requirements used by your plugin, like `mypy`, do not
            mix with the rest of your project. Read that option's help message for more info
            on resolves.
            """
        ),
    )
    extra_type_stubs = StrListOption(
        advanced=True,
        help=softwrap(
            """
            Extra type stub requirements to install when running MyPy.

            Normally, type stubs can be installed as typical requirements, such as putting
            them in `requirements.txt` or using a `python_requirement` target.
            Alternatively, you can use this option so that the dependencies are solely
            used when running MyPy and are not runtime dependencies.

            Expects a list of pip-style requirement strings, like
            `['types-requests==2.25.9']`.

            We recommend also enabling `[mypy].extra_type_stubs_lockfile` for a more reproducible
            build and less supply-chain security risk.
            """
        ),
    )
    extra_type_stubs_lockfile = StrOption(
        advanced=True,
        # Note that there is no default lockfile, as by default, extra_type_stubs is empty.
        default=NO_TOOL_LOCKFILE,
        help=softwrap(
            f"""
            Path to a lockfile for the option `[mypy].extra_type_stubs`.

            Set to the string `{NO_TOOL_LOCKFILE}` to opt out of using a lockfile. We
            do not recommend this if you use `[mypy].extra_type_stubs`, though, as lockfiles are
            essential for reproducible builds and supply-chain security.

            To use a lockfile, set this option to a file path relative to the
            build root, then run `{bin_name()} generate-lockfiles --resolve=mypy-extra-type-stubs`.
            """
        ),
    )

    @property
    def config_request(self) -> ConfigFilesRequest:
        # Refer to https://mypy.readthedocs.io/en/stable/config_file.html.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"{self.options_scope}.config",
            discovery=self.config_discovery,
            check_existence=["mypy.ini", ".mypy.ini"],
            check_content={"setup.cfg": b"[mypy", "pyproject.toml": b"[tool.mypy"},
        )

    @property
    def source_plugins(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(
            self._source_plugins,
            owning_address=None,
            description_of_origin=f"the option `[{self.options_scope}].source_plugins`",
        )

    def extra_type_stubs_pex_request(
        self, interpreter_constraints: InterpreterConstraints
    ) -> PexRequest:
        requirements: PexRequirements | EntireLockfile
        if self.extra_type_stubs_lockfile == NO_TOOL_LOCKFILE:
            requirements = PexRequirements(self.extra_type_stubs)
        else:
            tool_lockfile = ToolCustomLockfile(
                file_path=self.extra_type_stubs_lockfile,
                file_path_description_of_origin=(
                    f"the option `[{self.options_scope}].extra_type_stubs_lockfile`"
                ),
                lockfile_hex_digest=calculate_invalidation_digest(self.extra_type_stubs),
                resolve_name=MyPyExtraTypeStubsLockfileSentinel.resolve_name,
                uses_project_interpreter_constraints=True,
                uses_source_plugins=False,
            )
            requirements = EntireLockfile(tool_lockfile, complete_req_strings=self.extra_type_stubs)
        return PexRequest(
            output_filename="extra_type_stubs.pex",
            internal_only=True,
            requirements=requirements,
            interpreter_constraints=interpreter_constraints,
        )

    def check_and_warn_if_python_version_configured(self, config: FileContent | None) -> bool:
        """Determine if we can dynamically set `--python-version` and warn if not."""
        configured = []
        if config and b"python_version" in config.content:
            configured.append(
                softwrap(
                    f"""
                    `python_version` in {config.path} (which is used because of either config
                    discovery or the `[mypy].config` option)
                    """
                )
            )
        if "--py2" in self.args:
            configured.append("`--py2` in the `--mypy-args` option")
        if any(arg.startswith("--python-version") for arg in self.args):
            configured.append("`--python-version` in the `--mypy-args` option")
        if configured:
            formatted_configured = " and you set ".join(configured)
            logger.warning(
                softwrap(
                    f"""
                    You set {formatted_configured}. Normally, Pants would automatically set this
                    for you based on your code's interpreter constraints
                    ({doc_url('python-interpreter-compatibility')}). Instead, it will
                    use what you set.

                    (Allowing Pants to automatically set the option allows Pants to partition your
                    targets by their constraints, so that, for example, you can run MyPy on
                    Python 2-only code and Python 3-only code at the same time. It also allows Pants
                    to leverage MyPy's cache, making subsequent runs of MyPy very fast.
                    In the future, this feature may no longer work.)
                    """
                )
            )
        return bool(configured)


# --------------------------------------------------------------------------------------
# Config files
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MyPyConfigFile:
    digest: Digest
    _python_version_configured: bool

    def python_version_to_autoset(
        self, interpreter_constraints: InterpreterConstraints, interpreter_universe: Iterable[str]
    ) -> str | None:
        """If the user did not already set `--python-version`, return the major.minor version to
        use."""
        if self._python_version_configured:
            return None
        return interpreter_constraints.minimum_python_version(interpreter_universe)


@rule
async def setup_mypy_config(mypy: MyPy) -> MyPyConfigFile:
    config_files = await Get(ConfigFiles, ConfigFilesRequest, mypy.config_request)
    digest_contents = await Get(DigestContents, Digest, config_files.snapshot.digest)
    python_version_configured = mypy.check_and_warn_if_python_version_configured(
        digest_contents[0] if digest_contents else None
    )
    return MyPyConfigFile(config_files.snapshot.digest, python_version_configured)


# --------------------------------------------------------------------------------------
# First party plugins
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MyPyFirstPartyPlugins:
    requirement_strings: FrozenOrderedSet[str]
    sources_digest: Digest
    source_roots: tuple[str, ...]


@rule("Prepare [mypy].source_plugins", level=LogLevel.DEBUG)
async def mypy_first_party_plugins(
    mypy: MyPy,
) -> MyPyFirstPartyPlugins:
    if not mypy.source_plugins:
        return MyPyFirstPartyPlugins(FrozenOrderedSet(), EMPTY_DIGEST, ())

    plugin_target_addresses = await Get(Addresses, UnparsedAddressInputs, mypy.source_plugins)
    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest(plugin_target_addresses)
    )

    requirements = PexRequirements.req_strings_from_requirement_fields(
        (
            plugin_tgt[PythonRequirementsField]
            for plugin_tgt in transitive_targets.closure
            if plugin_tgt.has_field(PythonRequirementsField)
        ),
    )

    sources = await Get(PythonSourceFiles, PythonSourceFilesRequest(transitive_targets.closure))
    return MyPyFirstPartyPlugins(
        requirement_strings=requirements,
        sources_digest=sources.source_files.snapshot.digest,
        source_roots=sources.source_roots,
    )


# --------------------------------------------------------------------------------------
# Interpreter constraints
# --------------------------------------------------------------------------------------


@rule_helper
async def _mypy_interpreter_constraints(
    mypy: MyPy, python_setup: PythonSetup
) -> InterpreterConstraints:
    constraints = mypy.interpreter_constraints
    if mypy.options.is_default("interpreter_constraints"):
        code_constraints = await _find_all_unique_interpreter_constraints(
            python_setup, MyPyFieldSet
        )
        if code_constraints.requires_python38_or_newer(python_setup.interpreter_versions_universe):
            constraints = code_constraints
    return constraints


# --------------------------------------------------------------------------------------
# Lockfiles
# --------------------------------------------------------------------------------------


class MyPyLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = MyPy.options_scope


@rule(
    desc="Determine MyPy interpreter constraints (for lockfile generation)",
    level=LogLevel.DEBUG,
)
async def setup_mypy_lockfile(
    _: MyPyLockfileSentinel,
    first_party_plugins: MyPyFirstPartyPlugins,
    mypy: MyPy,
    python_setup: PythonSetup,
) -> GeneratePythonLockfile:
    if not mypy.uses_custom_lockfile:
        return GeneratePythonLockfile.from_tool(
            mypy, use_pex=python_setup.generate_lockfiles_with_pex
        )

    constraints = await _mypy_interpreter_constraints(mypy, python_setup)
    return GeneratePythonLockfile.from_tool(
        mypy,
        constraints,
        extra_requirements=first_party_plugins.requirement_strings,
        use_pex=python_setup.generate_lockfiles_with_pex,
    )


class MyPyExtraTypeStubsLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = "mypy-extra-type-stubs"


@rule(desc="Set up lockfile request for [mypy].extra_type_stubs", level=LogLevel.DEBUG)
async def setup_mypy_extra_type_stubs_lockfile(
    request: MyPyExtraTypeStubsLockfileSentinel,
    mypy: MyPy,
    python_setup: PythonSetup,
) -> GeneratePythonLockfile:
    use_pex = python_setup.generate_lockfiles_with_pex
    if mypy.extra_type_stubs_lockfile == NO_TOOL_LOCKFILE:
        return GeneratePythonLockfile(
            requirements=FrozenOrderedSet(),
            interpreter_constraints=InterpreterConstraints(),
            resolve_name=request.resolve_name,
            lockfile_dest=mypy.extra_type_stubs_lockfile,
            use_pex=use_pex,
        )

    # While MyPy will run in partitions, we need a set of constraints that works with every
    # partition.
    #
    # This first finds the ICs of each partition. Then, it ORs all unique resulting interpreter
    # constraints. The net effect is that every possible Python interpreter used will be covered.
    all_tgts = await Get(AllTargets, AllTargetsRequest())
    all_field_sets = [
        MyPyFieldSet.create(tgt) for tgt in all_tgts if MyPyFieldSet.is_applicable(tgt)
    ]
    resolve_and_interpreter_constraints_to_coarsened_targets = (
        await partition._by_interpreter_constraints_and_resolve(all_field_sets, python_setup)
    )
    unique_constraints = {
        ics for resolve, ics in resolve_and_interpreter_constraints_to_coarsened_targets.keys()
    }
    interpreter_constraints = InterpreterConstraints(
        itertools.chain.from_iterable(unique_constraints)
    ) or InterpreterConstraints(python_setup.interpreter_constraints)
    return GeneratePythonLockfile(
        requirements=FrozenOrderedSet(mypy.extra_type_stubs),
        interpreter_constraints=interpreter_constraints,
        resolve_name=request.resolve_name,
        lockfile_dest=mypy.extra_type_stubs_lockfile,
        use_pex=use_pex,
    )


# --------------------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------------------


class MyPyExportSentinel(ExportPythonToolSentinel):
    pass


@rule(desc="Determine MyPy interpreter constraints (for `export` goal)", level=LogLevel.DEBUG)
async def mypy_export(
    _: MyPyExportSentinel,
    mypy: MyPy,
    python_setup: PythonSetup,
    first_party_plugins: MyPyFirstPartyPlugins,
) -> ExportPythonTool:
    if not mypy.export:
        return ExportPythonTool(resolve_name=mypy.options_scope, pex_request=None)
    constraints = await _mypy_interpreter_constraints(mypy, python_setup)
    return ExportPythonTool(
        resolve_name=mypy.options_scope,
        pex_request=mypy.to_pex_request(
            interpreter_constraints=constraints,
            extra_requirements=first_party_plugins.requirement_strings,
        ),
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, MyPyLockfileSentinel),
        UnionRule(GenerateToolLockfileSentinel, MyPyExtraTypeStubsLockfileSentinel),
        UnionRule(ExportPythonToolSentinel, MyPyExportSentinel),
    )
