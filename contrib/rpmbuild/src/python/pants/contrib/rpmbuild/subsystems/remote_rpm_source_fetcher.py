# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.binaries.binary_util import BinaryUtil
from pants.fs.archive import archiver_for_path
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_dir
from pants.util.memo import memoized_property


class RemoteRpmSourceUtil(BinaryUtil):
  """Encapsulates access to hosted remote sources."""

  class RemoteRpmSourceNotFound(BinaryUtil.BinaryNotFound):
    """No file or bundle found at any registered baseurl."""

  class Factory(Subsystem):

    options_scope = 'binaries'

    @classmethod
    def create(cls):
      options = cls.global_instance().get_options()
      return RemoteRpmSourceUtil(
        options.binaries_baseurls, options.binaries_fetch_timeout_secs,
        options.pants_bootstrapdir, options.binaries_path_by_id)

  @staticmethod
  def uname_func():
    # Force pulling down linux paths, since this is destined to be built in a Docker container.
    return "linux", "foo", "bar", "baz", "x86_64"

  def select_binary(self, supportdir, version, name):
    # Enforces using the linux Docker environment since this is for rpmbuilder.
    # TODO(mateo): Derive the uname_func from the platfrom in the RpmBuilder.
    binary_path = self._select_binary_base_path(supportdir, version, name, uname_func=self.uname_func)
    return self._fetch_binary(name=name, binary_path=binary_path)


class RemoteRpmSourceFetcher(object):
  """Fetcher for remote sources which uses BinaryUtil pipeline."""
  # This allows long-lived caching of remote downloads, which are painful to to over and over when they aren't changing.

  class Factory(Subsystem):
    options_scope = 'remote-fetcher'

    @classmethod
    def subsystem_dependencies(cls):
      return super(RemoteRpmSourceFetcher.Factory, cls).subsystem_dependencies() + (BinaryUtil.Factory,)

    @classmethod
    def register_options(cls, register):
      register(
        '--supportdir',
        advanced=True,
        default='bin',
        help='Find sources under this dir.'
        'Used as part of the path to lookup the tool with --binary-util-baseurls and --pants-bootstrapdir',
      )

    def create(self, remote_target):
      remote_rpm_source_util = RemoteRpmSourceUtil.Factory.create()
      options = self.get_options()
      return RemoteRpmSourceFetcher(
        remote_rpm_source_util,
        options.supportdir,
        remote_target.namespace,
        remote_target.version,
        remote_target.filename,
        extract=remote_target.extract,
      )

  def __init__(self, remote_rpm_source_util, supportdir, namespace, version, filename, extract):
    self._supportdir = supportdir
    self._namespace = namespace
    self._filename = filename
    self._extract = extract or False

    self.remote_rpm_source_util = remote_rpm_source_util
    self.version = version

  @property
  def _relpath(self):
    return os.path.join(self._supportdir, self._namespace)

  @property
  def extracted(self):
    return self._extract

  def _construct_path(self):
    fetched = self.remote_rpm_source_util.select_binary(self._relpath, self.version, self._filename)
    if not self._extract:
      return fetched
    unpacked_dir = os.path.dirname(fetched)
    outdir = os.path.join(unpacked_dir, 'unpacked')
    if not os.path.exists(outdir):
      with temporary_dir(root_dir=unpacked_dir) as tmp_root:
        # This is an upstream lever that pattern matches the filepath to an archive type.
        archiver = archiver_for_path(fetched)
        archiver.extract(fetched, tmp_root)
        os.rename(tmp_root, outdir)
    return os.path.join(outdir)

  @memoized_property
  def path(self):
    """Fetch the binary and return the full file path.

    Safe to call repeatedly, the fetch itself is idempotent.
    """
    return self._construct_path()
