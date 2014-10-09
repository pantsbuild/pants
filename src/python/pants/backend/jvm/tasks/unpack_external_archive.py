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
from pants.backend.jvm.targets.external_archive import ExternalArchive
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot
from pants.base.source_root import SourceRoot
from pants.fs.archive import ZIP


from twitter.common.dirutil.fileset import fnmatch_translate_extended
from twitter.common.collections import OrderedSet, maybe_list


logger = logging.getLogger(__name__)


class UnpackExternalArchive(Task):

  class WrongTargetTypeError(Exception):
    """Thrown if a reference to a non external_archive is listed in the arguments.
    """

  class ExpectedAddressError(Exception):
    """Thrown if an object that is not an address is listed in the arguments.
    """

  def __init__(self, *args, **kwargs):
    super(UnpackExternalArchive, self).__init__(*args, **kwargs)
    self._buildroot = get_buildroot()

  def prepare(self, round_manager):
    super(UnpackExternalArchive, self).prepare(round_manager)
    round_manager.require_data('ivy_imports')

  def resolve_deps(self, key, default=[]):
    deps = OrderedSet()
    for dep in self.context.config.getlist('protobuf-gen', key, default=maybe_list(default)):
      if dep:
        try:
          deps.update(self.context.resolve(dep))
        except AddressLookupError as e:
          raise self.DepLookupError("{message}\n  referenced from [{section}] key: {key} in pants.ini"
                                    .format(message=e, section='protobuf-gen', key=key))
    return deps

  def _external_archive_unpack_dir(self, external_archive):
    return os.path.normpath(os.path.join(self._workdir, external_archive.id))

  def _unpack(self, external_archive):
    """
    :param ExternalArchive external_archive:
    """
    unpack_dir=self._external_archive_unpack_dir(external_archive)
    if os.path.exists(unpack_dir):
      shutil.rmtree(unpack_dir)
    if not os.path.exists(unpack_dir):
      os.makedirs(unpack_dir)

    include_patterns = [re.compile(fnmatch_translate_extended(i))
                        for i in external_archive.include_patterns]
    exclude_patterns = [re.compile(fnmatch_translate_extended(e))
                        for e in external_archive.exclude_patterns]

    def _unpack_filter(filename):
      if include_patterns:
        found = False
        for include_pattern in include_patterns:
          if include_pattern.match(filename):
            found = True
            break;
        if not found:
          return False
      if exclude_patterns:
        for exclude_pattern in exclude_patterns:
          if exclude_pattern.match(filename):
            return False
      return True

    products = self.context.products.get('ivy_imports')
    jarmap = products[external_archive]

    for path, names in jarmap.items():
      for name in names:
        jar_path = os.path.join(path, name)
        ZIP.extract(jar_path, unpack_dir, filter=_unpack_filter)

  def execute(self):
    def add_external_archives(target):
      if isinstance(target, ExternalArchive):
        external_archives.add(target)

    # All of this work would be much easier if source_set was a target.  Then it could do all
    # of this resolution itself instead of deferring it until this time.
    external_archives = set()
    targets = self.context.targets()
    addresses = [target.address for target in targets]

    self.context.build_graph.walk_transitive_dependency_graph(addresses, add_external_archives)
    for external_archive in external_archives:
      self._unpack(external_archive)
      unpack_dir = self._external_archive_unpack_dir(external_archive)
      SourceRoot.register(unpack_dir)
      found_files = []
      for root, dirs, files in os.walk(unpack_dir):
        for f in files:
          relpath = os.path.relpath(os.path.join(root, f), unpack_dir)
          found_files.append(relpath)
      rel_unpack_dir = unpack_dir[len(self._buildroot) + 1:]
      external_archive.populate(found_files, rel_path=rel_unpack_dir, source_root=unpack_dir)
