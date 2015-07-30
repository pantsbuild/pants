# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict
from io import BytesIO
from urllib2 import urlopen
from zipfile import ZipFile

from pants.base.exceptions import TaskError
from pants.util.dirutil import get_basedir, safe_mkdir, safe_open

from pants.contrib.go.targets.go_remote_package import GoRemotePackage
from pants.contrib.go.tasks.go_task import GoTask


class GoFetch(GoTask):
  """Downloads a 3rd party Go package."""

  @classmethod
  def product_types(cls):
    return ['go_remote_pkg_source']

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    self.context.products.safe_create_data('go_remote_pkg_source', lambda: defaultdict(str))
    with self.invalidated(self.context.targets(self.is_go_remote_pkg)) as invalidation_check:
      for vt in invalidation_check.invalid_vts:
        import_id = self.global_import_id(vt.target)
        rev = vt.target.payload.get_field_value('rev')
        zip_url = vt.target.payload.get_field_value('zip_url').format(id=import_id, rev=rev)
        if not zip_url:
          raise TaskError('No zip url specified for go_remote_package {id}'
                          .format(id=import_id))
        dest_dir = os.path.join(vt.results_dir, import_id)
        self._download_zip(zip_url, dest_dir)
        self.context.products.get_data('go_remote_pkg_source')[vt.target] = dest_dir

  def _download_zip(self, zip_url, dest_dir):
    """Downloads a zip file at the given URL into the given directory.

    :param zip_url string: Full URL pointing to zip file.
    :param dest_dir string: Absolute path of directory into which the unzipped contents
                            will be placed into, not including the zip directory itself.
    """
    safe_mkdir(dest_dir)
    stream = BytesIO(urlopen(zip_url).read())
    zfile = ZipFile(stream)
    for info in zfile.infolist():
      if info.filename.endswith('/'):
        # Skip directories.
        continue
      # Strip zip directory name from files.
      filename = os.path.relpath(info.filename, get_basedir(info.filename))
      f = safe_open(os.path.join(dest_dir, filename), 'w')
      f.write(zfile.read(info))
      f.close()
