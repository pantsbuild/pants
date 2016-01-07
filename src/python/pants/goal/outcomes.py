# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.workunit import WorkUnit


class Outcomes(object):
  """An object to keep track of the outcome of each workunit, store them in a little plaintext file, and produce a dict.

  This allows automation calling pants to determine which task failed.
  """

  def __init__(self):
    self._outcomes = {}

  def add_outcome(self, path, outcome):
    """Adds an outcome to this object.

    Converts the outcome to a string because the consumer is outside pants without access to WorkUnit.

    :param string path: colon-delimited path defining the workunit
    :param int outcome: WorkUnit.ABORTED, WorkUnit.SUCCESS, etc.
    """

    # Dict operations are thread-safe in CPython, so we can do this.
    # https://docs.python.org/2/glossary.html#term-global-interpreter-lock
    self._outcomes[path] = WorkUnit.outcome_string(outcome)

  def get_all(self):
    return self._outcomes
