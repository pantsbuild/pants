# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
import json

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.exceptions import TaskError


class Attributes(ConsoleTask):
  """Show the attributes platform and language for the given targets.
  """

  @classmethod
  def prepare(cls, options, round_manager):
    super(Attributes, cls).prepare(options, round_manager)

  @classmethod
  def register_options(cls, register):
    super(Attributes, cls).register_options(register)

  def __init__(self, *args, **kwargs):
    super(Attributes, self).__init__(*args, **kwargs)

  def console_output(self, targets):
    if not targets:
      raise TaskError("Please specify a target.")
    yield json.dumps(self._find_attributes(), indent=2)

  def _find_attributes(self):
    metadata = collections.defaultdict(dict)
    for target in self.context.target_roots:
      for (key, val) in [self._language(target), self._platform(target)]:
        if val:
          metadata[target.address.spec][key] = val
    return metadata

  def _language(self, target):
    language = None
    if target.is_java:
      language = 'java'
    elif target.is_python:
      language = 'python'
    elif target.is_scala:
      language = 'scala'
    return ('language', language)

  def _platform(self, target):
    platform = None
    if target.is_jvm:
      platform = 'jvm'
    elif target.is_python:
      platform = 'python'
    return ('platform', platform)
