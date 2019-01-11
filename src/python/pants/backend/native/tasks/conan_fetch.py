# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import os
import re

from pants.backend.native.config.environment import Platform
from pants.backend.native.targets.external_native_library import ExternalNativeLibrary
from pants.backend.native.targets.packaged_native_library import PackagedNativeLibrary
from pants.backend.native.tasks.conan_prep import ConanPrep
from pants.base.build_environment import get_pants_cachedir
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.dirutil import mergetree, safe_concurrent_creation, safe_file_dump
from pants.util.memo import memoized_property


class ConanFetch(SimpleCodegenTask):

  gentarget_type = ExternalNativeLibrary

  sources_globs = ('include/**/*', 'lib/*',)

  @property
  def validate_sources_present(self):
    return False

  def synthetic_target_type(self, target):
    return PackagedNativeLibrary

  default_remotes = {
    'conan-center': 'https://conan.bintray.com',
  }

  @classmethod
  def register_options(cls, register):
    super(ConanFetch, cls).register_options(register)
    register('--conan-remotes', type=dict, default=cls.default_remotes, advanced=True,
             fingerprint=True,
             help='The conan remotes to download conan packages from.')

  @classmethod
  def implementation_version(cls):
    return super(ConanFetch, cls).implementation_version() + [('ConanFetch', 1)]

  @classmethod
  def prepare(cls, options, round_manager):
    super(ConanFetch, cls).prepare(options, round_manager)
    round_manager.require_data(ConanPrep.tool_instance_cls)

  class ConanFetchError(TaskError): pass

  @memoized_property
  def _conan_user_home(self):
    user_home_base = os.path.join(get_pants_cachedir(), 'conan-support', 'conan-user-home')
    # Find a specific subdirectory of the pants shared cachedir specific to this task's option
    # values.
    user_home = os.path.join(user_home_base, self.fingerprint)
    # Write a file overriding the conan remote's configuration with this task's options. See
    # https://docs.conan.io/en/latest/reference/commands/consumer/config.html#conan-config-install
    # for docs on configuring remotes.
    remotes_txt = os.path.join(user_home, 'remotes.txt')
    if not os.path.isfile(remotes_txt):
      with safe_concurrent_creation(remotes_txt) as remotes_path:
        remotes_description = '{}\n'.format('\n'.join(
          '{name} {url} {is_ssl}'.format(
            name=name,
            url=url,
            is_ssl=re.match(r'^https://', url) is not None)
          for name, url in self.get_options().conan_remotes.items()))
        safe_file_dump(remotes_path, remotes_description, binary_mode=False)
    return user_home

  @memoized_property
  def _conan_os_name(self):
    return Platform.create().resolve_platform_specific({
      'darwin': lambda: 'Macos',
      'linux': lambda: 'Linux',
    })

  @property
  def _copy_target_attributes(self):
    basic_attributes = [a for a in super(ConanFetch, self)._copy_target_attributes
                        if a != 'provides']
    return basic_attributes + [
      'include_relpath',
      'lib_relpath',
      'native_lib_names',
    ]

  def execute_codegen(self, target, target_workdir):
    """
    Invoke the conan pex to fetch conan packages specified by a
    `ExternalLibLibrary` target.

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
        'install',
        conan_requirement.pkg_spec,
        '--settings', 'os={}'.format(self._conan_os_name),
      ]
      for remote in self.get_options().conan_remotes:
        argv.extend(['--remote', remote])

      workunit_factory = functools.partial(
        self.context.new_workunit,
        name='install-conan-{}'.format(conan_requirement.pkg_spec),
        labels=[WorkUnitLabel.TOOL])
      # CONAN_USER_HOME is somewhat documented at
      # https://docs.conan.io/en/latest/mastering/sharing_settings_and_config.html.
      env = {
        'CONAN_USER_HOME': self._conan_user_home,
      }

      with conan.run_with(workunit_factory, argv, env=env) as (cmdline, exit_code, workunit):
        if exit_code != 0:
          raise self.ConanFetchError(
            'Error performing conan install with argv {} and environment {}: exited non-zero ({}).'
            .format(cmdline, env, exit_code),
            exit_code=exit_code)

        # Read the stdout from the read-write buffer, from the beginning of the output.
        conan_install_stdout = workunit.output('stdout').read_from(0)
        pkg_sha = conan_requirement.parse_conan_stdout_for_pkg_sha(conan_install_stdout)

      installed_data_dir = os.path.join(
        self._conan_user_home,
        '.conan', 'data',
        conan_requirement.directory_path,
        'package',
        pkg_sha)

      # Copy over the contents of the installed package into the target output directory. These
      # paths are currently hardcoded -- see `ExternalNativeLibrary`.
      mergetree(os.path.join(installed_data_dir, conan_requirement.include_relpath),
                os.path.join(target_workdir, 'include'))
      mergetree(os.path.join(installed_data_dir, conan_requirement.lib_relpath),
                os.path.join(target_workdir, 'lib'))
