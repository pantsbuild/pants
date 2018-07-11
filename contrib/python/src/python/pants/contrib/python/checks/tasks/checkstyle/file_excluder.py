# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re

from pants.base.deprecated import deprecated_conditional
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

            deprecated_conditional(
              lambda: 'pep8' in plugins,
              '1.10.0.dev0',
              'The pep8 check has been renamed to pycodestyle. '
              'Please update your suppression file: "{}". The pep8 option'.format(excludes_path)
            )
            map(lambda p:p if p != 'pep8' else 'pycodestyle', plugins)

            self.excludes[pattern] = {
              'regex': re.compile(pattern),
              'plugins': plugins
            }
            log.debug('Exclude pattern: {pattern}'.format(pattern=pattern))
    else:
      log.debug('No excludes file specified. All python sources will be checked.')

  def should_include(self, source_filename, plugin):
    for exclude_rule in self.excludes.values():
      if exclude_rule['regex'].match(source_filename) and (
        (exclude_rule['plugins'] == ['.*']) or (plugin in exclude_rule['plugins'])
      ):
        return False
    return True
