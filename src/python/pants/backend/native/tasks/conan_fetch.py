# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import os
import re

from pants.backend.native.targets.external_native_library import ExternalNativeLibrary
from pants.backend.native.targets.packaged_native_library import PackagedNativeLibrary
from pants.backend.native.tasks.conan_prep import ConanPrep
from pants.base.build_environment import get_pants_cachedir
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.engine.platform import Platform
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import mergetree, safe_file_dump, safe_mkdir
from pants.util.enums import match
from pants.util.memo import memoized_property


class ConanFetch(SimpleCodegenTask):

    gentarget_type = ExternalNativeLibrary

    sources_globs = (
        "include/**/*",
        "lib/*",
    )

    @property
    def validate_sources_present(self):
        return False

    def synthetic_target_type(self, target):
        return PackagedNativeLibrary

    default_remotes = {
        "conan-center": "https://conan.bintray.com",
    }

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--conan-remotes",
            type=dict,
            default=cls.default_remotes,
            advanced=True,
            fingerprint=True,
            help="The conan remotes to download conan packages from.",
        )

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("ConanFetch", 1)]

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data(ConanPrep.tool_instance_cls)

    class ConanConfigError(TaskError):
        pass

    class ConanFetchError(TaskError):
        pass

    @property
    def _remotes_txt_content(self):
        """Generate a file containing overrides for Conan remotes which get applied to
        registry.json."""
        return "{}\n".format(
            "\n".join(
                "{name} {url} {is_ssl}".format(
                    name=name, url=url, is_ssl=re.match(r"^https://", url) is not None
                )
                for name, url in self.get_options().conan_remotes.items()
            )
        )

    def _conan_user_home(self, conan, in_workdir=False):
        """Create the CONAN_USER_HOME for this task fingerprint and initialize the Conan remotes.

        See https://docs.conan.io/en/latest/reference/commands/consumer/config.html#conan-config-install
        for docs on configuring remotes.
        """
        # This argument is exposed so tests don't leak out of the workdir.
        if in_workdir:
            base_cache_dir = self.workdir
        else:
            base_cache_dir = get_pants_cachedir()
        user_home_base = os.path.join(base_cache_dir, "conan-support", "conan-user-home")
        # Locate the subdirectory of the pants shared cachedir specific to this task's option values.
        user_home = os.path.join(user_home_base, self.fingerprint)
        conan_install_base = os.path.join(user_home, ".conan")
        # Conan doesn't copy remotes.txt into the .conan subdir after the "config install" command, it
        # simply edits registry.json. However, it is valid to have this file there, and Conan won't
        # touch it, so we use its presence to detect whether we have appropriately initialized the
        # Conan installation.
        remotes_txt_sentinel = os.path.join(conan_install_base, "remotes.txt")
        if not os.path.isfile(remotes_txt_sentinel):
            safe_mkdir(conan_install_base)
            # Conan doesn't consume the remotes.txt file just by being in the conan directory -- we need
            # to create another directory containing any selection of files detailed in
            # https://docs.conan.io/en/latest/reference/commands/consumer/config.html#conan-config-install
            # and "install" from there to our desired conan directory.
            with temporary_dir() as remotes_install_dir:
                # Create an artificial conan configuration dir containing just remotes.txt.
                remotes_txt_for_install = os.path.join(remotes_install_dir, "remotes.txt")
                safe_file_dump(remotes_txt_for_install, self._remotes_txt_content)
                # Configure the desired user home from this artificial config dir.
                argv = ["config", "install", remotes_install_dir]
                workunit_factory = functools.partial(
                    self.context.new_workunit,
                    name="initial-conan-config",
                    labels=[WorkUnitLabel.TOOL],
                )
                env = {
                    "CONAN_USER_HOME": user_home,
                }
                cmdline, exit_code = conan.run(workunit_factory, argv, env=env)
                if exit_code != 0:
                    raise self.ConanConfigError(
                        "Error configuring conan with argv {} and environment {}: exited non-zero ({}).".format(
                            cmdline, env, exit_code
                        ),
                        exit_code=exit_code,
                    )
            # Generate the sentinel file so that we know the remotes have been successfully configured for
            # this particular task fingerprint in successive pants runs.
            safe_file_dump(remotes_txt_sentinel, self._remotes_txt_content)

        return user_home

    @memoized_property
    def _conan_os_name(self):
        return match(Platform.current, {Platform.darwin: "Macos", Platform.linux: "Linux"})

    @property
    def _copy_target_attributes(self):
        basic_attributes = [a for a in super()._copy_target_attributes if a != "provides"]
        return basic_attributes + [
            "include_relpath",
            "lib_relpath",
            "native_lib_names",
        ]

    def execute_codegen(self, target, target_workdir):
        """Invoke the conan pex to fetch conan packages specified by a `ExternalNativeLibrary`
        target.

        :param ExternalNativeLibrary target: a target containing conan package specifications.
        :param str target_workdir: where to copy the installed package contents to.
        """
        conan = self.context.products.get_data(ConanPrep.tool_instance_cls)

        # TODO: we should really be able to download all of these in one go, and we should make an
        # upstream PR to allow that against Conan if not.
        for conan_requirement in target.packages:
            # See https://docs.conan.io/en/latest/reference/commands/consumer/install.html for
            # documentation on the 'install' command.
            argv = [
                "install",
                conan_requirement.pkg_spec,
                "--settings",
                "os={}".format(self._conan_os_name),
            ]
            for remote in self.get_options().conan_remotes:
                argv.extend(["--remote", remote])

            workunit_factory = functools.partial(
                self.context.new_workunit,
                name="install-conan-{}".format(conan_requirement.pkg_spec),
                labels=[WorkUnitLabel.TOOL],
            )
            # CONAN_USER_HOME is somewhat documented at
            # https://docs.conan.io/en/latest/mastering/sharing_settings_and_config.html.
            user_home = self._conan_user_home(conan)
            env = {
                "CONAN_USER_HOME": user_home,
            }

            with conan.run_with(workunit_factory, argv, env=env) as (cmdline, exit_code, workunit):
                if exit_code != 0:
                    raise self.ConanFetchError(
                        "Error performing conan install with argv {} and environment {}: exited non-zero ({}).".format(
                            cmdline, env, exit_code
                        ),
                        exit_code=exit_code,
                    )

                # Read the stdout from the read-write buffer, from the beginning of the output, and convert
                # to unicode.
                conan_install_stdout = workunit.output("stdout").read_from(0).decode()
                pkg_sha = conan_requirement.parse_conan_stdout_for_pkg_sha(conan_install_stdout)

            installed_data_dir = os.path.join(
                user_home, ".conan", "data", conan_requirement.directory_path, "package", pkg_sha
            )

            # Copy over the contents of the installed package into the target output directory. These
            # paths are currently hardcoded -- see `ExternalNativeLibrary`.
            mergetree(
                os.path.join(installed_data_dir, conan_requirement.include_relpath),
                os.path.join(target_workdir, "include"),
            )
            mergetree(
                os.path.join(installed_data_dir, conan_requirement.lib_relpath),
                os.path.join(target_workdir, "lib"),
            )
