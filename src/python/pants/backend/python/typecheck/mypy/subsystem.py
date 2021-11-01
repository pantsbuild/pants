# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from typing import Iterable, cast

from pants.backend.python.goals.lockfile import PythonLockfileRequest, PythonToolLockfileSentinel
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    ConsoleScript,
    PythonRequirementsField,
    PythonSourceField,
)
from pants.backend.python.typecheck.mypy.skip_field import SkipMyPyField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequirements
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import EMPTY_DIGEST, Digest, DigestContents, FileContent
from pants.engine.rules import Get, MultiGet, collect_rules, rule
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
from pants.util.docutil import doc_url, git_url
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MyPyFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    sources: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipMyPyField).value


# --------------------------------------------------------------------------------------
# Subsystem
# --------------------------------------------------------------------------------------


class MyPy(PythonToolBase):
    options_scope = "mypy"
    help = "The MyPy Python type checker (http://mypy-lang.org/)."

    default_version = "mypy==0.910"
    default_main = ConsoleScript("mypy")

    # See `mypy/rules.py`. We only use these default constraints in some situations.
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.typecheck.mypy", "lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/python/typecheck/mypy/lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)
    uses_requirements_from_source_plugins = True

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=f"Don't use MyPy when running `{register.bootstrap.pants_bin_name} typecheck`.",
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to mypy, e.g. "
                f'`--{cls.options_scope}-args="--python-version 3.7 --disallow-any-expr"`'
            ),
        )
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help=(
                "Path to a config file understood by MyPy "
                "(https://mypy.readthedocs.io/en/stable/config_file.html).\n\n"
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
                "runs (`mypy.ini`, `.mypy.ini`, and `setup.cfg`)."
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
                "plugins.\n\nYou must also set `plugins = path.to.module` in your `mypy.ini`, and "
                "set the `[mypy].config` option in your `pants.toml`.\n\nTo instead load "
                "third-party plugins, set the option `[mypy].extra_requirements` and set the "
                "`plugins` option in `mypy.ini`."
            ),
        )
        register(
            "--extra-type-stubs",
            type=list,
            member_type=str,
            advanced=True,
            help=(
                "Extra type stub requirements to install when running MyPy.\n\n"
                "Normally, type stubs can be installed as typical requirements, such as putting "
                "them in `requirements.txt` or using a `python_requirement_library` target."
                "Alternatively, you can use this option so that the dependencies are solely "
                "used when running MyPy and are not runtime dependencies.\n\n"
                "Expects a list of pip-style requirement strings, like "
                "`['types-requests==2.25.9']`."
            ),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> tuple[str, ...]:
        return tuple(self.options.args)

    @property
    def extra_type_stubs(self) -> tuple[str, ...]:
        return tuple(self.options.extra_type_stubs)

    @property
    def config(self) -> str | None:
        return cast("str | None", self.options.config)

    @property
    def config_request(self) -> ConfigFilesRequest:
        # Refer to https://mypy.readthedocs.io/en/stable/config_file.html.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"{self.options_scope}.config",
            discovery=cast(bool, self.options.config_discovery),
            check_existence=["mypy.ini", ".mypy.ini"],
            check_content={"setup.cfg": b"[mypy", "pyproject.toml": b"[tool.mypy"},
        )

    @property
    def source_plugins(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(self.options.source_plugins, owning_address=None)

    def check_and_warn_if_python_version_configured(self, config: FileContent | None) -> bool:
        """Determine if we can dynamically set `--python-version` and warn if not."""
        configured = []
        if config and b"python_version" in config.content:
            configured.append(
                f"`python_version` in {config.path} (which is used because of either config "
                "discovery or the `[mypy].config` option)"
            )
        if "--py2" in self.args:
            configured.append("`--py2` in the `--mypy-args` option")
        if any(arg.startswith("--python-version") for arg in self.args):
            configured.append("`--python-version` in the `--mypy-args` option")
        if configured:
            formatted_configured = " and you set ".join(configured)
            logger.warning(
                f"You set {formatted_configured}. Normally, Pants would automatically set this "
                "for you based on your code's interpreter constraints "
                f"({doc_url('python-interpreter-compatibility')}). Instead, it will "
                "use what you set.\n\n"
                "(Automatically setting the option allows Pants to partition your targets by their "
                "constraints, so that, for example, you can run MyPy on Python 2-only code and "
                "Python 3-only code at the same time. This feature may no longer work.)"
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
async def mypy_first_party_plugins(mypy: MyPy) -> MyPyFirstPartyPlugins:
    if not mypy.source_plugins:
        return MyPyFirstPartyPlugins(FrozenOrderedSet(), EMPTY_DIGEST, ())

    plugin_target_addresses = await Get(Addresses, UnparsedAddressInputs, mypy.source_plugins)
    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest(plugin_target_addresses)
    )

    requirements = PexRequirements.create_from_requirement_fields(
        plugin_tgt[PythonRequirementsField]
        for plugin_tgt in transitive_targets.closure
        if plugin_tgt.has_field(PythonRequirementsField)
    )

    sources = await Get(PythonSourceFiles, PythonSourceFilesRequest(transitive_targets.closure))
    return MyPyFirstPartyPlugins(
        requirement_strings=requirements.req_strings,
        sources_digest=sources.source_files.snapshot.digest,
        source_roots=sources.source_roots,
    )


# --------------------------------------------------------------------------------------
# Lockfile
# --------------------------------------------------------------------------------------


class MyPyLockfileSentinel(PythonToolLockfileSentinel):
    options_scope = MyPy.options_scope


@rule(
    desc="Determine if MyPy should use Python 3.8+ (for lockfile usage)",
    level=LogLevel.DEBUG,
)
async def setup_mypy_lockfile(
    _: MyPyLockfileSentinel,
    first_party_plugins: MyPyFirstPartyPlugins,
    mypy: MyPy,
    python_setup: PythonSetup,
) -> PythonLockfileRequest:
    if not mypy.uses_lockfile:
        return PythonLockfileRequest.from_tool(mypy)

    constraints = mypy.interpreter_constraints
    if mypy.options.is_default("interpreter_constraints"):
        all_tgts = await Get(AllTargets, AllTargetsRequest())
        all_transitive_targets = await MultiGet(
            Get(TransitiveTargets, TransitiveTargetsRequest([tgt.address]))
            for tgt in all_tgts
            if MyPyFieldSet.is_applicable(tgt)
        )
        unique_constraints = {
            InterpreterConstraints.create_from_targets(transitive_targets.closure, python_setup)
            for transitive_targets in all_transitive_targets
        }
        code_constraints = InterpreterConstraints(itertools.chain.from_iterable(unique_constraints))
        if code_constraints.requires_python38_or_newer(python_setup.interpreter_universe):
            constraints = code_constraints

    return PythonLockfileRequest.from_tool(
        mypy, constraints, extra_requirements=first_party_plugins.requirement_strings
    )


def rules():
    return (*collect_rules(), UnionRule(PythonToolLockfileSentinel, MyPyLockfileSentinel))
