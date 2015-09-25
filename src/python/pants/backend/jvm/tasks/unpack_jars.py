# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import re
import shutil
from hashlib import sha1

from twitter.common.dirutil.fileset import fnmatch_translate_extended

from pants.backend.core.tasks.task import Task
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.backend.jvm.tasks.jar_import_products import JarImportProducts
from pants.base.build_environment import get_buildroot
from pants.base.fingerprint_strategy import DefaultFingerprintHashingMixin, FingerprintStrategy
from pants.fs.archive import ZIP


logger = logging.getLogger(__name__)


class UnpackJarsFingerprintStrategy(DefaultFingerprintHashingMixin, FingerprintStrategy):

  def compute_fingerprint(self, target):
    """UnpackedJars targets need to be re-unpacked if any of its configuration changes or any of
    the jars they import have changed.
    """
    if isinstance(target, UnpackedJars):
      hasher = sha1()
      for cache_key in sorted(jar.cache_key() for jar in target.imported_jars):
        hasher.update(cache_key)
      hasher.update(target.payload.fingerprint())
      return hasher.hexdigest()
    return None


class UnpackJars(Task):
  """Looks for UnpackedJars targets and unpacks them.

  Adds an entry to SourceRoot for the contents.
  """

  class InvalidPatternError(Exception):
    """Raised if a pattern can't be compiled for including or excluding args"""

  class MissingUnpackedDirsError(Exception):
    """Raised if a directory that is expected to be unpacked doesn't exist."""

  @classmethod
  def product_types(cls):
    return ['unpacked_archives']

  @classmethod
  def prepare(cls, options, round_manager):
    super(UnpackJars, cls).prepare(options, round_manager)
    round_manager.require_data(JarImportProducts)

  def _unpack_dir(self, unpacked_jars):
    return os.path.normpath(os.path.join(self._workdir, unpacked_jars.id))

  @classmethod
  def _file_filter(cls, filename, include_patterns, exclude_patterns):
    """:returns: `True` if the file should be allowed through the filter."""
    for exclude_pattern in exclude_patterns:
      if exclude_pattern.match(filename):
        return False
    if include_patterns:
      found = False
      for include_pattern in include_patterns:
        if include_pattern.match(filename):
          found = True
          break
      if not found:
        return False
    return True

  @classmethod
  def _compile_patterns(cls, patterns, field_name="Unknown", spec="Unknown"):
    compiled_patterns = []
    for p in patterns:
      try:
        compiled_patterns.append(re.compile(fnmatch_translate_extended(p)))
      except (TypeError, re.error) as e:
        raise cls.InvalidPatternError(
          'In {spec}, "{field_value}" in {field_name} can\'t be compiled: {msg}'
          .format(field_name=field_name, field_value=p, spec=spec, msg=e))
    return compiled_patterns

  @classmethod
  def calculate_unpack_filter(cls, includes=None, excludes=None, spec=None):
    """Take regex patterns and return a filter function.

    :param list includes: List of include patterns to pass to _file_filter.
    :param list excludes: List of exclude patterns to pass to _file_filter.
    """
    include_patterns = cls._compile_patterns(includes or [],
                                             field_name='include_patterns',
                                             spec=spec)
    exclude_patterns = cls._compile_patterns(excludes or [],
                                             field_name='exclude_patterns',
                                             spec=spec)
    return lambda f: cls._file_filter(f, include_patterns, exclude_patterns)

  # TODO(mateor) move unpack code that isn't jar-specific to fs.archive or an Unpack base class.
  @classmethod
  def get_unpack_filter(cls, unpacked_jars):
    """Calculate a filter function from the include/exclude patterns of a Target.

    :param Target unpacked_jars: A target with include_patterns and exclude_patterns attributes.
    """
    return cls.calculate_unpack_filter(includes=unpacked_jars.include_patterns,
                                       excludes=unpacked_jars.exclude_patterns,
                                       spec=unpacked_jars.address.spec)

  def _unpack(self, unpacked_jars):
    """Extracts files from the downloaded jar files and places them in a work directory.

    :param UnpackedJars unpacked_jars: target referencing jar_libraries to unpack.
    """
    unpack_dir = self._unpack_dir(unpacked_jars)
    if os.path.exists(unpack_dir):
      shutil.rmtree(unpack_dir)
    if not os.path.exists(unpack_dir):
      os.makedirs(unpack_dir)

    unpack_filter = self.get_unpack_filter(unpacked_jars)
    jar_import_products = self.context.products.get_data(JarImportProducts)
    for coordinate, jar_path in jar_import_products.imports(unpacked_jars):
      self.context.log.debug('Unpacking jar {coordinate} from {jar_path} to {unpack_dir}.'
                             .format(coordinate=coordinate,
                                     jar_path=jar_path,
                                     unpack_dir=unpack_dir))
      ZIP.extract(jar_path, unpack_dir, filter_func=unpack_filter)

  def execute(self):
    addresses = [target.address for target in self.context.targets()]
    closure = self.context.build_graph.transitive_subgraph_of_addresses(addresses)
    unpacked_jars_list = [t for t in closure if isinstance(t, UnpackedJars)]

    unpacked_targets = []
    with self.invalidated(unpacked_jars_list,
                          fingerprint_strategy=UnpackJarsFingerprintStrategy(),
                          invalidate_dependents=True) as invalidation_check:
      if invalidation_check.invalid_vts:
        unpacked_targets.extend([vt.target for vt in invalidation_check.invalid_vts])
        for target in unpacked_targets:
          self._unpack(target)

    for unpacked_jars_target in unpacked_jars_list:
      unpack_dir = self._unpack_dir(unpacked_jars_target)
      if not (os.path.exists(unpack_dir) and os.path.isdir(unpack_dir)):
        raise self.MissingUnpackedDirsError(
          "Expected {unpack_dir} to exist containing unpacked files for {target}"
          .format(unpack_dir=unpack_dir, target=unpacked_jars_target.address.spec))
      found_files = []
      for root, dirs, files in os.walk(unpack_dir):
        for f in files:
          relpath = os.path.relpath(os.path.join(root, f), unpack_dir)
          found_files.append(relpath)
      rel_unpack_dir = os.path.relpath(unpack_dir, get_buildroot())
      unpacked_sources_product = self.context.products.get_data('unpacked_archives', lambda: {})
      unpacked_sources_product[unpacked_jars_target] = [found_files, rel_unpack_dir]

    # Returning the list of unpacked targets for testing purposes
    return unpacked_targets
