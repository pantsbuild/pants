# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from contextlib import contextmanager

from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_open


logger = logging.getLogger(__name__)


@contextmanager
def safe_args(args,
              options,
              max_args=None,
              argfile=None,
              delimiter='\n',
              quoter=None,
              delete=True):
  """Yields args if there are less than a limit otherwise writes args to an argfile and yields an
  argument list with one argument formed from the path of the argfile.

  :param args: The args to work with.
  :param OptionValueContainer options: scoped options object for this task
  :param max_args: The maximum number of args to let though without writing an argfile.  If not
    specified then the maximum will be loaded from the --max-subprocess-args option.
  :param argfile: The file to write args to when there are too many; defaults to a temporary file.
  :param delimiter: The delimiter to insert between args written to the argfile, defaults to '\n'
  :param quoter: A function that can take the argfile path and return a single argument value;
    defaults to: <code>lambda f: '@' + f<code>
  :param delete: If True deletes any arg files created upon exit from this context; defaults to
    True.
  """
  max_args = max_args or options.max_subprocess_args
  if len(args) > max_args:
    def create_argfile(f):
      logger.debug('Creating argfile {} with contents {}'.format(f.name, ' '.join(args)))
      f.write(delimiter.join(args))
      f.close()
      return [quoter(f.name) if quoter else '@{}'.format(f.name)]

    if argfile:
      try:
        with safe_open(argfile, 'w') as fp:
          yield create_argfile(fp)
      finally:
        if delete and os.path.exists(argfile):
          os.unlink(argfile)
    else:
      with temporary_file(cleanup=delete) as fp:
        yield create_argfile(fp)
  else:
    yield args
