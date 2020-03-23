# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import filecmp
import logging
import os.path
import shutil
from typing import Tuple

from pants.option.custom_types import dir_option, file_option
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_mkdir, safe_rmtree

logger = logging.getLogger(__name__)


class ESLint(Subsystem):
    options_scope = "eslint"

    required_files = ["yarn.lock", "package.json"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register("--version", default="4.15.0", fingerprint=True, help="Use this ESLint version.")
        register(
            "--config",
            type=file_option,
            default=None,
            help="Path to `.eslintrc` or alternative ESLint config file",
        )
        register(
            "--skip",
            type=bool,
            default=False,
            help="Don't use ESLint when running `./pants fmt` and `./pants lint`",
        )
        register(
            "--setupdir",
            type=dir_option,
            fingerprint=True,
            help="Find the package.json and yarn.lock under this dir for installing eslint and plugins.",
        )
        register(
            "--ignore",
            type=file_option,
            fingerprint=True,
            help="The path to the global eslint ignore path",
        )

    def configure(self, *, bootstrapped_support_path: str) -> None:
        logger.debug(
            f"Copying {self.options.setupdir} to bootstrapped dir: {bootstrapped_support_path}"
        )
        safe_rmtree(bootstrapped_support_path)
        shutil.copytree(self.options.setupdir, bootstrapped_support_path)

    def supportdir(self, *, task_workdir: str) -> Tuple[str, bool]:
        """Returns the path where the ESLint is bootstrapped.

        :param task_workdir: The task's working directory
        :returns: The path where ESLint is bootstrapped and whether or not it is configured
        """
        bootstrapped_support_path = os.path.join(task_workdir, "eslint")

        # TODO(nsaechao): Should only have to check if the "eslint" dir exists in the task_workdir
        # assuming fingerprinting works as intended.

        # If the eslint_setupdir is not provided or missing required files, then
        # clean up the directory so that Pants can install a pre-defined eslint version later on.
        # Otherwise, if there is no configurations changes, rely on the cache.
        # If there is a config change detected, use the new configuration.
        if self.options.setupdir:
            configured = all(
                os.path.exists(os.path.join(self.options.setupdir, f)) for f in self.required_files
            )
        else:
            configured = False
        if not configured:
            safe_mkdir(bootstrapped_support_path, clean=True)
        else:
            try:
                installed = all(
                    filecmp.cmp(
                        os.path.join(self.options.setupdir, f),
                        os.path.join(bootstrapped_support_path, f),
                    )
                    for f in self.required_files
                )
            except OSError:
                installed = False

            if not installed:
                self.configure(bootstrapped_support_path=bootstrapped_support_path)
        return bootstrapped_support_path, configured
