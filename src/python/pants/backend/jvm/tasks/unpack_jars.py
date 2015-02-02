# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import logging
import os
import re
import shutil

from pants.backend.core.tasks.task import Task
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.base.build_environment import get_buildroot
from pants.fs.archive import ZIP

from twitter.common.dirutil.fileset import fnmatch_translate_extended


logger = logging.getLogger(__name__)


class UnpackJars(Task):
  """Looks for UnpackedJars targets and unpacks them.

     Adds an entry to SourceRoot for the contents.  Initially only
     supported by JavaProtobufLibrary.
  """

  class InvalidPatternError(Exception):
    """Thrown if a pattern can't be compiled for including or excluding args"""

  @classmethod
  def product_types(cls):
    return ['unpacked_archives']

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('ivy_imports')

  def __init__(self, *args, **kwargs):
    super(UnpackJars, self).__init__(*args, **kwargs)
    self._buildroot = get_buildroot()

  def _unpack_dir(self, unpacked_jars):
    return os.path.normpath(os.path.join(self._workdir, unpacked_jars.id))

  @classmethod
  def _unpack_filter(cls, filename, include_patterns, exclude_patterns):
    """:return: True if the file should be allowed through the filter"""
    found = False
    if include_patterns:
      for include_pattern in include_patterns:
        if include_pattern.match(filename):
          found = True
          break
      if not found:
        return False
    if exclude_patterns:
      for exclude_pattern in exclude_patterns:
        if exclude_pattern.match(filename):
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

  def _unpack(self, unpacked_jars):
    """Extracts files from the downloaded jar files and places them in a work directory.

    :param UnpackedJars unpacked_jars: target referencing jar_libraries to unpack.
    """
    unpack_dir = self._unpack_dir(unpacked_jars)
    if os.path.exists(unpack_dir):
      shutil.rmtree(unpack_dir)
    if not os.path.exists(unpack_dir):
      os.makedirs(unpack_dir)

    include_patterns = self._compile_patterns(unpacked_jars.include_patterns,
                                              field_name='include_patterns',
                                              spec=unpacked_jars.address.spec)
    exclude_patterns = self._compile_patterns(unpacked_jars.exclude_patterns,
                                              field_name='exclude_patterns',
                                              spec=unpacked_jars.address.spec)

    unpack_filter = lambda f: self._unpack_filter(f, include_patterns, exclude_patterns)
    products = self.context.products.get('ivy_imports')
    jarmap = products[unpacked_jars]

    for path, names in jarmap.items():
      for name in names:
        jar_path = os.path.join(path, name)
        ZIP.extract(jar_path, unpack_dir,
                    filter_func=unpack_filter)

  def execute(self):
    addresses = [target.address for target in self.context.targets()]
    unpacked_jars_list = [t for t in self.context.build_graph.transitive_subgraph_of_addresses(addresses)
                     if isinstance(t, UnpackedJars)]
    for unpacked_jars_target in unpacked_jars_list:
      self._unpack(unpacked_jars_target)
      unpack_dir = self._unpack_dir(unpacked_jars_target)
      found_files = []
      for root, dirs, files in os.walk(unpack_dir):
        for f in files:
          relpath = os.path.relpath(os.path.join(root, f), unpack_dir)
          found_files.append(relpath)
      rel_unpack_dir = os.path.relpath(unpack_dir, self._buildroot)
      unpacked_sources_product = self.context.products.get_data('unpacked_archives', lambda: {})
      unpacked_sources_product[unpacked_jars_target] = [found_files, rel_unpack_dir]
