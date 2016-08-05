# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import subprocess

from pants.backend.python.tasks.python_task import PythonTask
from pants.binaries.binary_util import BinaryUtil
from pants.option.custom_types import file_option


class IsortPythonTask(PythonTask):
  """Task to provide autoformat with python isort module."""

  _PYTHON_SOURCE_EXTENSION = '.py'

  def __init__(self, *args, **kwargs):
    super(IsortPythonTask, self).__init__(*args, **kwargs)
    self.options = self.get_options()

  @classmethod
  def register_options(cls, register):
    super(IsortPythonTask, cls).register_options(register)
    register('--skip', type=bool, default=False,
             help='If enabled, skip isort task.')
    register('--config-file', fingerprint=True, type=file_option, default='./.isort.cfg',
             help='Specify path to isort config file.')
    register('--version', advanced=True, fingerprint=True, default='4.2.5', help='Version of isort.')
    register('--passthrough-args', fingerprint=True, default=None,
             help='Once specified, any other option passed to isort binary will be ignored. '
                  'Reference: https://github.com/timothycrosley/isort/blob/develop/isort/main.py')

  def execute(self):
    """Run isort on all found source python files."""
    if self.options.skip:
      return

    isort_script = BinaryUtil.Factory.create().select_script('scripts/isort', self.options.version, 'isort.pex')

    if self.options.passthrough_args is not None:
      cmd = [isort_script] + self.options.passthrough_args.split(' ')
      logging.info(cmd)
      try:
        subprocess.check_call(cmd)
      except subprocess.CalledProcessError as e:
        logging.error(e)

    else:
      sources = self._calculate_sources(self.context.targets())

      cmd = [isort_script,
             '--settings-path={}'.format(self.options.config_file),
             ' '.join(sources),
             ]
      logging.info(cmd)
      subprocess.check_call(cmd)

      # with self.context.new_workunit(name='cloc',
      #                                labels=[WorkUnitLabel.TOOL],
      #                                cmd=' '.join(cmd)) as workunit:
      #   result = subprocess.call(cmd,
      #                            stdout=workunit.output('stdout'),
      #                            stderr=workunit.output('stderr'))

      # if result != 0:
      #   raise TaskError('{} ... exited non-zero ({}).'.format(' '.join(cmd), result))

  def _calculate_sources(self, targets):
    """Generate a set of source files from the given targets."""
    sources = set()
    for target in targets:
      sources.update(
        source for source in target.sources_relative_to_buildroot()
        if os.path.splitext(source)[1] == self._PYTHON_SOURCE_EXTENSION
      )
    return sources

# if __name__ == '__main__':
#   sys.argv[0] = re.sub(r'(-script\.pyw|\.exe)?$', '', sys.argv[0])
#   sys.exit(main())
