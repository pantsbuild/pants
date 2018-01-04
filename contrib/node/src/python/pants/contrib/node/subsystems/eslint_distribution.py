# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import logging
import os
import shutil

from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_mkdir, safe_rmtree

logger = logging.getLogger(__name__)

class ESLintDistribution(object):
  """Represents a self-bootstrapping ESLint distribution."""

  ESLINT_DISTRIBUTION_MODULE = 'synthetic-install-eslint-distribution-module'

  class Factory(Subsystem):
    options_scope = 'eslint-distribution'

    @classmethod
    def register_options(cls, register):
      super(ESLintDistribution.Factory, cls).register_options(register)
      register('--setupdir', advanced=True, fingerprint=True,
               help='Find the package.json under this dir for installing eslint and plugins.')
      register('--supportdir', advanced=True, default='bin/eslint',
               help='Find the ESLint distribution under this dir.')
      register('--eslint-config', advanced=True, fingerprint=True,
               help='The path to the global eslint configuration file specifying all the rules')
      register('--eslint-ignore', advanced=True, fingerprint=True,
               help='The path to the global eslint ignore path')
    def create(cls):
      # NB: create is an instance method used to globally scope this subsystem.
      options = cls.get_options()
      global_options = cls.global_instance().get_options()
      pants_bootstrapdir = global_options.pants_bootstrapdir
      return ESLintDistribution(options.setupdir, options.supportdir, options.eslint_config,
                                options.eslint_ignore, pants_bootstrapdir)

  @property
  def setupdir(self):
    return self._setupdir

  @property
  def supportdir(self):
    return self._supportdir

  @property
  def eslint_config(self):
    return self._eslint_config

  @property
  def eslint_ignore(self):
    return self._eslint_ignore

  @property
  def pants_bootstrapdir(self):
    return self._pants_bootstrapdir

  def __init__(self, setupdir, supportdir, eslint_config, eslint_ignore, pants_bootstrapdir):
    self._setupdir = setupdir
    self._supportdir = supportdir
    self._eslint_config = eslint_config or None
    self._eslint_ignore = eslint_ignore or None
    self._pants_bootstrapdir = pants_bootstrapdir

  def _is_workingdir_valid(self, workingdir):
    dir_exists = os.path.isdir(workingdir)
    if not dir_exists:
      return False
    else:
      lock_file = os.path.join(workingdir, 'yarn.lock')
      package_json = os.path.join(workingdir, 'package.json')
      if not os.path.isfile(package_json):
        logger.warning('The workingdir: `{}` is missing a package.json'.format(workingdir))
        return False
      elif not os.path.isfile(lock_file):
        logger.warning('A lock file was not found, consider adding a yarn.lock file for '
                       'deterministic installation.')
    return True

  def _compare_file_checksums(self, file_a, file_b):
    if os.path.isfile(file_a) and os.path.isfile(file_b):
      return self._checksum_md5(file_a) == self._checksum_md5(file_b)
    return False

  def _checksum_md5(self, filename):
    md5 = hashlib.md5()
    with open(filename, 'rb') as f:
      for block in iter(lambda: f.read(128 * md5.block_size), b''):
        md5.update(block)
    return md5.hexdigest()

  def _bootstrap_eslinter(self, bootstrapped_support_path):
    if self._setupdir is None or not self._is_workingdir_valid(self._setupdir):
      safe_mkdir(bootstrapped_support_path)
      return False
    logger.debug('Copying {setupdir} to bootstrapped dir: {support_path}'
                           .format(setupdir=self._setupdir, support_path=bootstrapped_support_path))
    safe_rmtree(bootstrapped_support_path)
    shutil.copytree(self._setupdir, bootstrapped_support_path)
    return True

  def fetch_supportdir(self):
    """ Returns the path where the ESLintDistribution is bootstrapped.

    :returns: The path where ESLintDistribution is bootstrapped and whether or not it was preconfigured
    :rtype: (string, bool)
    """
    bootstrap_dir = os.path.realpath(os.path.expanduser(self._pants_bootstrapdir))
    bootstrapped_support_path = os.path.join(bootstrap_dir, self._supportdir)
    is_preconfigured = True
    if not os.path.exists(bootstrapped_support_path):
     is_preconfigured = self._bootstrap_eslinter(bootstrapped_support_path)
    else:
      if not self._is_workingdir_valid(bootstrapped_support_path):
        is_preconfigured = self._bootstrap_eslinter(bootstrapped_support_path)
      elif self._setupdir is not None and self._is_workingdir_valid(self._setupdir):
        setup_lock_file = os.path.join(self._setupdir, 'yarn.lock')
        setup_package_json = os.path.join(self.setupdir, 'package.json')
        bootstrapped_lock_file = os.path.join(bootstrapped_support_path, 'yarn.lock')
        bootstrapped_package_json = os.path.join(bootstrapped_support_path, 'package.json')
        if not self._compare_file_checksums(setup_package_json, bootstrapped_package_json):
          is_preconfigured = self._bootstrap_eslinter(bootstrapped_support_path)
        elif os.path.isfile(setup_lock_file) and not self._compare_file_checksums(setup_lock_file, bootstrapped_lock_file):
          is_preconfigured = self._bootstrap_eslinter(bootstrapped_support_path)

    return (bootstrapped_support_path, is_preconfigured)
