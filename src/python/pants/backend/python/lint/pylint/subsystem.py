# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.engine.addresses import UnparsedAddressInputs
from pants.option.custom_types import file_option, shell_str, target_option
from pants.util.docutil import docs_url


class Pylint(PythonToolBase):
    options_scope = "pylint"
    help = "The Pylint linter for Python code (https://www.pylint.org/)."

    default_version = "pylint>=2.4.4,<2.5"
    default_entry_point = "pylint"

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
            help="Path to `pylintrc` or alternative Pylint config file",
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
                f"{docs_url('source-roots')}\n\nYou must also set `load-plugins=$module_name` in "
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
    def args(self) -> List[str]:
        return cast(List[str], self.options.args)

    @property
    def config(self) -> Optional[str]:
        return cast(Optional[str], self.options.config)

    @property
    def source_plugins(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(self.options.source_plugins, owning_address=None)
