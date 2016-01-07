# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.workunit import WorkUnit
from pants.util.dirutil import safe_mkdir_for


class Outcomes(object):
  """An object to keep track of the outcome of each workunit, store them in a little plaintext file, and produce a dict.

  This allows automation calling pants to determine which task failed.
  """

  def __init__(self, path):
    self._path = path
    safe_mkdir_for(self._path)
    self._outcomes = {}

  def add_outcome(self, path, outcome):
    """Adds an outcome to this object.

    Converts the outcome to a string because the consumer is outside pants without access to WorkUnit.

    :param string path: colon-delimited path defining the workunit
    :param int outcome: WorkUnit.ABORTED, WorkUnit.SUCCESS, etc.
    """
    self._outcomes[path] = WorkUnit.outcome_string(outcome)
    # Check existence in case we're a clean-all. We don't want to write anything in that case.
    if self._path and os.path.exists(os.path.dirname(self._path)):
      with open(self._path, 'w') as f:
        for key, value in self.get_all().items():
          f.write('{key}: {value}\n'.format(key=key, value=value))

  def get_all(self):
    return self._outcomes
