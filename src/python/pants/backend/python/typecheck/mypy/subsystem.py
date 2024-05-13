# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.python.goals import lockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonRequirementsField,
    PythonResolveField,
    PythonSourceField,
)
from pants.backend.python.typecheck.mypy.skip_field import SkipMyPyField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.partition import _find_all_unique_interpreter_constraints
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import EMPTY_DIGEST, Digest, DigestContents, FileContent
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, Target, TransitiveTargets, TransitiveTargetsRequest
from pants.option.option_types import (
    ArgsListOption,
    BoolOption,
    FileOption,
    SkipOption,
    TargetListOption,
)
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MyPyFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    sources: PythonSourceField
    resolve: PythonResolveField
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
    help_short = "The MyPy Python type checker (http://mypy-lang.org/)."

    default_main = ConsoleScript("mypy")
    default_requirements = ["mypy>=0.961,<2"]

    # See `mypy/rules.py`. We only use these default constraints in some situations.
    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.typecheck.mypy", "mypy.lock")

    skip = SkipOption("check")
    args = ArgsListOption(example="--python-version 3.7 --disallow-any-expr")
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
            f"""
            An optional list of `python_sources` target addresses to load first-party plugins.

            You must also set `plugins = path.to.module` in your `mypy.ini`, and
            set the `[mypy].config` option in your `pants.toml`.

            To instead load third-party plugins, set the option `[mypy].install_from_resolve`
            to a resolve whose lockfile includes those plugins, and set the `plugins` option
            in `mypy.ini`.  See {doc_url('docs/python/goals/check')}.
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
                    ({doc_url('docs/python/overview/interpreter-compatibility')}). Instead, it will
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


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
    )
