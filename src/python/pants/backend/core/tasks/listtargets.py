# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.exceptions import TaskError


class ListTargets(ConsoleTask):
  """Lists all targets matching the target specs.

  If no targets are specified, lists all targets in the workspace.
  """

  @classmethod
  def register_options(cls, register):
    super(ListTargets, cls).register_options(register)
    register('--provides', action='store_true', default=False,
             help='List only targets that provide an artifact, displaying the columns specified by '
                  '--provides-columns.')
    register('--provides-columns', default='address,artifact_id',
             help='Display these columns when --provides is specified. Available columns are: '
                  'address, artifact_id, repo_name, repo_url, push_db_basedir')
    register('--documented', action='store_true', default=False,
             help='Print only targets that are documented with a description.')

  def __init__(self, *args, **kwargs):
    super(ListTargets, self).__init__(*args, **kwargs)

    self._provides = self.get_options().provides
    self._provides_columns = self.get_options().provides_columns
    self._documented = self.get_options().documented

  def console_output(self, targets):
    if self._provides:
      def extract_artifact_id(target):
        provided_jar, _ = target.get_artifact_info()
        return '{0}#{1}'.format(provided_jar.org, provided_jar.name)

      extractors = dict(
          address=lambda target: target.address.spec,
          artifact_id=extract_artifact_id,
          repo_name=lambda target: target.provides.repo.name,
          repo_url=lambda target: target.provides.repo.url,
          push_db_basedir=lambda target: target.provides.repo.push_db_basedir,
      )

      def print_provides(column_extractors, target):
        if target.is_exported:
          return ' '.join(extractor(target) for extractor in column_extractors)

      try:
        column_extractors = [extractors[col] for col in (self._provides_columns.split(','))]
      except KeyError:
        raise TaskError('Invalid columns specified: {0}. Valid columns are: address, artifact_id, '
                        'repo_name, repo_url, push_db_basedir.'.format(self._provides_columns))

      print_fn = lambda target: print_provides(column_extractors, target)
    elif self._documented:
      def print_documented(target):
        if target.description:
          return '{0}\n  {1}'.format(target.address.spec,
                                     '\n  '.join(target.description.strip().split('\n')))
      print_fn = print_documented
    else:
      print_fn = lambda target: target.address.spec

    visited = set()
    for target in self._targets():
      result = print_fn(target)
      if result and result not in visited:
        visited.add(result)
        yield result

  def _targets(self):
    if self.context.target_roots:
      return self.context.target_roots
    else:
      return self.context.scan().targets()
