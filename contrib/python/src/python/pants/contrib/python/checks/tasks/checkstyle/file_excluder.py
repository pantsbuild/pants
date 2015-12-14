# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.base.exceptions import TaskError


class FileExcluder(object):
  def __init__(self, excludes_path, log):
    self.excludes = {}
    if excludes_path:
      if not os.path.exists(excludes_path):
        raise TaskError('Excludes file does not exist: {0}'.format(excludes_path))
      with open(excludes_path) as fh:
        for line in fh.readlines():
          if line and not line.startswith('#') and '::' in line:
            pattern, plugins = line.strip().split('::', 2)
            plugins = plugins.split()

            self.excludes[pattern] = {
              'regex': re.compile(pattern),
              'plugins': plugins
            }
            log.debug('Exclude pattern: {pattern}'.format(pattern=pattern))
    else:
      log.debug('No excludes file specified. All scala sources will be checked.')

  def should_include(self, source_filename, plugin):
    for exclude_rule in self.excludes.values():
      if exclude_rule['regex'].match(source_filename) and (
        (exclude_rule['plugins'] == ['.*']) or (plugin in exclude_rule['plugins'])
      ):
        return False
    return True
