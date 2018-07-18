# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
from distutils.dir_util import copy_tree

from pants.backend.native.config.environment import Platform
from pants.backend.native.subsystems.conan import Conan
from pants.backend.native.targets.external_native_library import ExternalNativeLibrary
from pants.base.exceptions import TaskError
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.task.task import Task
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property
from pants.util.objects import Exactly, datatype
from pants.util.process_handler import subprocess


class ConanRequirement(datatype(['pkg_spec'])):
  """A wrapper class to encapsulate a Conan package requirement."""

  CONAN_OS_NAME = {
    'darwin': lambda: 'Macos',
    'linux': lambda: 'Linux',
  }

  def parse_conan_stdout_for_pkg_sha(self, stdout):
    # FIXME: properly regex this method.
    # https://github.com/pantsbuild/pants/issues/6168
    pkg_line = stdout.split('Packages')[1]
    collected_matches = [line for line in pkg_line.split() if self.pkg_spec in line]
    pkg_sha = collected_matches[0].split(':')[1]
    return pkg_sha

  @memoized_property
  def directory_path(self):
    """
    A helper method for converting Conan to package specifications to the data directory
    path that Conan creates for each package.

    Example package specification:
      "my_library/1.0.0@pants/stable"
    Example of the direcory path that Conan downloads pacakge data for this package to:
      "my_library/1.0.0/pants/stable"

    For more info on Conan package specifications, see:
      https://docs.conan.io/en/latest/introduction.html
    """
    return self.pkg_spec.replace('@', '/')

  @memoized_property
  def fetch_cmdline_args(self):
    platform = Platform.create()
    conan_os_name = platform.resolve_platform_specific(self.CONAN_OS_NAME)
    args = ['install', self.pkg_spec, '-s', 'os={}'.format(conan_os_name)]
    return args


class NativeExternalLibraryFetch(Task):
  options_scope = 'native-external-library-fetch'
  native_library_constraint = Exactly(ExternalNativeLibrary)

  class NativeExternalLibraryFetchError(TaskError):
    pass

  class NativeExternalLibraryFiles(object):
    def __init__(self):
      self.include_dir = None
      self.lib_dir = None
      self.lib_names = []

    def add_lib_name(self, lib_name):
      self.lib_names.append(lib_name)

    def get_third_party_lib_args(self):
      lib_args = []
      if self.lib_names:
        for lib_name in self.lib_names:
          lib_args.append('-l{}'.format(lib_name))
        lib_dir_arg = '-L{}'.format(self.lib_dir)
        lib_args.append(lib_dir_arg)
      return lib_args

  @classmethod
  def _parse_lib_name_from_library_filename(cls, filename):
    match_group = re.match(r"^lib(.*)\.(a|so|dylib)$", filename)
    if match_group:
      return match_group.group(1)
    return None

  @classmethod
  def register_options(cls, register):
    super(NativeExternalLibraryFetch, cls).register_options(register)
    register('--conan-remotes', type=list, default=['https://conan.bintray.com'], advanced=True,
             fingerprint=True, help='The conan remote to download conan packages from.')

  @classmethod
  def subsystem_dependencies(cls):
    return super(NativeExternalLibraryFetch, cls).subsystem_dependencies() + (Conan.scoped(cls),)

  @classmethod
  def product_types(cls):
    return [cls.NativeExternalLibraryFiles]

  @property
  def cache_target_dirs(self):
    return True

  @memoized_property
  def _conan_binary(self):
    return Conan.scoped_instance(self).bootstrap_conan()

  def execute(self):
    task_product = self.context.products.get_data(self.NativeExternalLibraryFiles,
                                                  self.NativeExternalLibraryFiles)

    native_lib_tgts = self.context.targets(self.native_library_constraint.satisfied_by)
    if native_lib_tgts:
      with self.invalidated(native_lib_tgts,
                            invalidate_dependents=True) as invalidation_check:
        resolve_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)
        vts_results_dir = self._prepare_vts_results_dir(resolve_vts)
        if invalidation_check.invalid_vts or not resolve_vts.valid:
          for vt in invalidation_check.all_vts:
            self._fetch_packages(vt, vts_results_dir)
        self._populate_task_product(vts_results_dir, task_product)

  def _prepare_vts_results_dir(self, vts):
    """
    Given a `VersionedTargetSet`, prepare its results dir.
    """
    vt_set_results_dir = os.path.join(self.workdir, vts.cache_key.hash)
    safe_mkdir(vt_set_results_dir)
    return vt_set_results_dir

  def _populate_task_product(self, results_dir, task_product):
    """
    Sets the relevant properties of the task product (`NativeExternalLibraryFiles`) object.
    """
    lib = os.path.join(results_dir, 'lib')
    include = os.path.join(results_dir, 'include')

    if os.path.exists(lib):
      task_product.lib_dir = lib
      for filename in os.listdir(lib):
        lib_name = self._parse_lib_name_from_library_filename(filename)
        if lib_name:
          task_product.add_lib_name(lib_name)

    if os.path.exists(include):
      task_product.include_dir = include

  def _get_conan_data_dir_path_for_package(self, pkg_dir_path, pkg_sha):
    return os.path.join(self.workdir,
                        '.conan',
                        'data',
                        pkg_dir_path,
                        'package',
                        pkg_sha)

  def _remove_conan_center_remote_cmdline(self, conan_binary):
    return conan_binary.pex.cmdline(['remote',
                                     'remove',
                                     'conan-center'])

  def _add_pants_conan_remote_cmdline(self, conan_binary, remote_index_num, remote_url):
    return conan_binary.pex.cmdline(['remote',
                                      'add',
                                      'pants-conan-remote-' + str(remote_index_num),
                                      remote_url,
                                      '--insert'])

  def ensure_conan_remote_configuration(self, conan_binary):
    """
    Ensure that the conan registry.txt file is sanitized and loaded with
    a pants-specific remote for package fetching.

    :param conan_binary: The conan client pex to use for manipulating registry.txt.
    """

    # Conan will prepend the conan-center remote to the remote registry when
    # bootstrapped for the first time, so we want to delete it from the registry
    # and replace it with Pants-controlled remotes.
    remove_conan_center_remote_cmdline = self._remove_conan_center_remote_cmdline(conan_binary)
    try:
      # Slice the command line because subprocess errors when the first element in the
      # list of command strings is the setting of an environment variable.
      stdout = subprocess.check_output(remove_conan_center_remote_cmdline.split()[1:])
      self.context.log.debug(stdout)
    except subprocess.CalledProcessError as e:
      if not "'conan-center' not found in remotes" in e.output:
        raise TaskError('Error deleting conan-center from conan registry: {}'.format(e.output))

    # Add the pants-specific conan remote.
    index_num = 0
    for remote_url in reversed(self.get_options().conan_remotes):
      index_num += 1
      # NB: --insert prepends a remote to conan's remote list. We reverse the options remote
      # list to maintain a sensible default for conan emote search order.
      add_pants_conan_remote_cmdline = self._add_pants_conan_remote_cmdline(conan_binary,
                                                                            index_num,
                                                                            remote_url)
      try:
        stdout = subprocess.check_output(add_pants_conan_remote_cmdline.split()[1:])
        self.context.log.debug(stdout)
      except subprocess.CalledProcessError as e:
        if not "already exists in remotes" in e.output:
          raise TaskError('Error adding pants-specific conan remote: {}'.format(e.output))

  def _copy_package_contents_from_conan_dir(self, results_dir, conan_requirement, pkg_sha):
    """
    Copy the contents of the fetched package into the results directory of the versioned
    target from the conan data directory.

    :param results_dir: A results directory to copy conan package contents to.
    :param conan_requirement: The `ConanRequirement` object that produced the package sha.
    :param pkg_sha: The sha of the local conan package corresponding to the specification.
    """
    src = self._get_conan_data_dir_path_for_package(conan_requirement.directory_path, pkg_sha)
    src_lib = os.path.join(src, 'lib')
    src_include = os.path.join(src, 'include')
    dest_lib = os.path.join(results_dir, 'lib')
    dest_include = os.path.join(results_dir, 'include')
    if os.path.exists(src_lib):
      copy_tree(src_lib, dest_lib)
    if os.path.exists(src_include):
      copy_tree(src_include, dest_include)

  def _fetch_packages(self, vt, vts_results_dir):
    """
    Invoke the conan pex to fetch conan packages specified by a
    `ExternalLibLibrary` target.

    :param vt: a versioned target containing conan package specifications.
    :param vts_results_dir: the results directory of the VersionedTargetSet
      for the purpose of aggregating package contents.
    """

    # NB: CONAN_USER_HOME specifies the directory to use for the .conan data directory.
    # This will initially live under the workdir to provide easy debugging on the initial
    # iteration of this system (a 'clean-all' will nuke the conan dir). In the future,
    # it would be good to migrate this under ~/.cache/pants/conan for persistence.
    # Fix this per: https://github.com/pantsbuild/pants/issues/6169
    with environment_as(CONAN_USER_HOME=self.workdir):
      for pkg_spec in vt.target.packages:

        conan_requirement = ConanRequirement(pkg_spec=pkg_spec)

        # Prepare conan command line and ensure remote is configured properly.
        self.ensure_conan_remote_configuration(self._conan_binary)
        args = conan_requirement.fetch_cmdline_args
        cmdline = self._conan_binary.pex.cmdline(args)

        self.context.log.debug('Running conan.pex cmdline: {}'.format(cmdline))
        self.context.log.debug('Conan remotes: {}'.format(self.get_options().conan_remotes))

        # Invoke conan to pull package from remote.
        try:
          stdout = subprocess.check_output(cmdline.split()[1:])
        except subprocess.CalledProcessError as e:
          raise self.NativeExternalLibraryFetchError(
            "Error invoking conan for fetch task: {}\n".format(e.output)
          )

        pkg_sha = conan_requirement.parse_conan_stdout_for_pkg_sha(stdout)
        self._copy_package_contents_from_conan_dir(vts_results_dir, conan_requirement, pkg_sha)
