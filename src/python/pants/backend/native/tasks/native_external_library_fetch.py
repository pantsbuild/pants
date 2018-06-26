# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from distutils.dir_util import copy_tree

from pants.backend.native.subsystems.conan import Conan
from pants.backend.native.targets.external_native_library import ExternalNativeLibrary
from pants.base.exceptions import TaskError
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.task.task import Task
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property
from pants.util.objects import Exactly
from pants.util.osutil import get_normalized_os_name
from pants.util.process_handler import subprocess


class ConanRequirement(object):
  """A wrapper class to encapsulate a Conan package requirement."""

  @staticmethod
  def _translate_conan_pkg_id_to_directory_path(pkg_string):
    return pkg_string.replace('@', '/')

  @staticmethod
  def _build_conan_cmdline_args(pkg_spec, os_name=None):
    os_name = os_name or get_normalized_os_name()
    conan_os_opt = None
    if os_name == 'linux':
      conan_os_opt = 'Linux'
    elif os_name == 'darwin':
      conan_os_opt = 'Macos'
    else:
      raise ValueError('Unsupported platform: {}'.format(conan_os_opt))
    args = ['install', pkg_spec]
    if conan_os_opt:
      args.extend(['-s', 'os=' + conan_os_opt])
    return args

  @classmethod
  def parse(cls, conan_pkg_spec):
    directory_path = cls._translate_conan_pkg_id_to_directory_path(conan_pkg_spec)
    fetch_cmdline_args = cls._build_conan_cmdline_args(conan_pkg_spec)
    return cls(conan_pkg_spec, directory_path, fetch_cmdline_args)

  def __init__(self, pkg_spec, directory_path, fetch_cmdline_args):
    self.pkg_spec = pkg_spec
    self.directory_path = directory_path
    self.fetch_cmdline_args = fetch_cmdline_args

  def parse_conan_stdout_for_pkg_sha(self, stdout):
    # TODO(cmlivingston): regex this
    pkg_line = stdout.split('Packages')[1]
    collected_matches = [line for line in pkg_line.split() if self.pkg_spec in line]
    pkg_sha = collected_matches[0].split(':')[1]
    return pkg_sha


class NativeExternalLibraryFetch(Task):
  options_scope = 'native-external-library-fetch'
  native_library_constraint = Exactly(ExternalNativeLibrary)

  class NativeExternalLibraryFetchError(TaskError):
    pass

  class NativeExternalLibraryFiles(object):
    def __init__(self):
      self._include = None
      self._lib = None
      self._lib_names = []

    @property
    def include(self):
      return self._include

    @include.setter
    def include(self, include_dir):
      self._include = include_dir

    @property
    def lib(self):
      return self._lib

    @lib.setter
    def lib(self, lib_dir):
      self._lib = lib_dir

    @property
    def lib_names(self):
      return self._lib_names

    def add_lib_name(self, lib_name):
      self._lib_names.append(lib_name)

  @staticmethod
  def _parse_lib_name_from_library_filename(filename):
    match_group = re.match( r"^lib(.*)\.(a|so|dylib)$", filename)
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
    return super(NativeExternalLibraryFetch, cls).subsystem_dependencies() + (Conan,)

  @classmethod
  def product_types(cls):
    return [cls.NativeExternalLibraryFiles]

  @property
  def cache_target_dirs(self):
    return True

  @memoized_property
  def _conan_binary(self):
    return Conan.global_instance().bootstrap_conan()

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
    Given a `VergetTargetSet`, prepare its results dir.
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
      task_product.lib = lib
      for filename in os.listdir(lib):
        lib_name = self._parse_lib_name_from_library_filename(filename)
        if lib_name:
          task_product.add_lib_name(lib_name)

    if os.path.exists(include):
      task_product.include = include

  def ensure_conan_remote_configuration(self, conan_binary):
    """
    Ensure that the conan registry.txt file is sanitized and loaded with
    a pants-specific remote for package fetching.

    :param conan_binary: The conan client pex to use for manipulating registry.txt.
    """

    # Delete the conan-center remote from conan's registry.
    remove_conan_center_remote_cmdline = conan_binary.pex.cmdline(['remote',
                                                                   'remove',
                                                                   'conan-center'])
    try:
      stdout = subprocess.check_output(remove_conan_center_remote_cmdline.split())
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
      add_pants_conan_remote_cmdline = conan_binary.pex.cmdline(['remote',
                                                                 'add',
                                                                 'pants-conan-remote-' + str(index_num),
                                                                 remote_url,
                                                                 '--insert'])
      try:
        stdout = subprocess.check_output(add_pants_conan_remote_cmdline.split())
        self.context.log.debug(stdout)
      except subprocess.CalledProcessError as e:
        if not "already exists in remotes" in e.output:
          raise TaskError('Error adding pants-specific conan remote: {}'.format(e.output))

  def _copy_package_contents_from_conan_dir(self, results_dir, conan_requirement, pkg_sha):
    """
    Copy the contents of the fetched pacakge into the results directory of the versioned
    target from the conan data directory.

    :param results_dir: A results directory to copy conan package contents to.
    :param conan_requirement: The `ConanRequirement` object that produced the package sha.
    :param pkg_sha: The sha of the local conan package corresponding to the specification.
    """
    src = os.path.join(os.path.join(self.workdir, '.conan'),
                       'data',
                       conan_requirement.directory_path,
                       'package',
                       pkg_sha)
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
    with environment_as(CONAN_USER_HOME=self.workdir):
      for pkg_spec in vt.target.packages:

        conan_requirement = ConanRequirement.parse(pkg_spec)

        # Prepare conan command line and ensure remote is configured properly.
        self.ensure_conan_remote_configuration(self._conan_binary)
        args = conan_requirement.fetch_cmdline_args
        cmdline = self._conan_binary.pex.cmdline(args)

        self.context.log.debug('Running conan.pex cmdline: {}'.format(cmdline))
        self.context.log.debug('Conan remotes: {}'.format(self.get_options().conan_remotes))

        # Invoke conan to pull package from remote.
        try:
          stdout = subprocess.check_output(cmdline.split())
        except subprocess.CalledProcessError as e:
          raise self.NativeExternalLibraryFetchError(
            "Error invoking conan for fetch task: {}\n".format(e.output)
          )

        pkg_sha = conan_requirement.parse_conan_stdout_for_pkg_sha(stdout)
        self._copy_package_contents_from_conan_dir(vts_results_dir, conan_requirement, pkg_sha)
