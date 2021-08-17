# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.fs import Digest, DigestContents, FileContent
from pants.engine.rules import Get, collect_rules, rule
from pants.option.custom_types import file_option, shell_str, target_option
from pants.python.python_setup import PythonSetup
from pants.util.docutil import doc_url

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Subsystem
# --------------------------------------------------------------------------------------


class MyPy(PythonToolBase):
    options_scope = "mypy"
    help = "The MyPy Python type checker (http://mypy-lang.org/)."

    default_version = "mypy==0.910"
    default_main = ConsoleScript("mypy")
    # See `mypy/rules.py`. We only use these default constraints in some situations. Technically,
    # MyPy only requires 3.5+, but some popular plugins like `django-stubs` require 3.6+. Because
    # 3.5 is EOL, and users can tweak this back, this seems like a more sensible default.
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]

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
                "An optional list of `python_library` target addresses to load first-party "
                "plugins.\n\nYou must also set `plugins = path.to.module` in your `mypy.ini`, and "
                "set the `[mypy].config` option in your `pants.toml`.\n\nTo instead load "
                "third-party plugins, set the option `[mypy].extra_requirements` and set the "
                "`plugins` option in `mypy.ini`."
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
async def setup_mypy_config(mypy: MyPy, python_setup: PythonSetup) -> MyPyConfigFile:
    config_files = await Get(ConfigFiles, ConfigFilesRequest, mypy.config_request)
    digest_contents = await Get(DigestContents, Digest, config_files.snapshot.digest)
    python_version_configured = mypy.check_and_warn_if_python_version_configured(
        digest_contents[0] if digest_contents else None
    )
    return MyPyConfigFile(config_files.snapshot.digest, python_version_configured)


def rules():
    return collect_rules()
