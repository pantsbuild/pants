# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.exceptions import TaskError
from pants.backend.core.tasks.console_task import ConsoleTask


class ListTargets(ConsoleTask):
  """Lists all targets matching the target specs.

  If no targets are specified, lists all targets in the workspace.
  """
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(ListTargets, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(
        mkflag('provides'),
        action='store_true',
        dest='list_provides', default=False,
        help='Specifies only targets that provide an artifact should be '
        'listed. The output will be 2 columns in this case: '
        '[target address] [artifact id]')

    option_group.add_option(
        mkflag('provides-columns'),
        dest='list_provides_columns',
        default='address,artifact_id',
        help='Specifies the columns to include in listing output when '
        'restricting the listing to targets that provide an artifact. '
        'Available columns are: address, artifact_id, repo_name, repo_url '
        'and repo_db')

    option_group.add_option(
        mkflag('documented'),
        action='store_true',
        dest='list_documented',
        default=False,
        help='Prints only targets that are documented with a description.')

  def __init__(self, *args, **kwargs):
    super(ListTargets, self).__init__(*args, **kwargs)

    self._provides = self.context.options.list_provides
    self._provides_columns = self.context.options.list_provides_columns
    self._documented = self.context.options.list_documented

  def console_output(self, targets):
    if self._provides:
      def extract_artifact_id(target):
        provided_jar, _, _ = target.get_artifact_info()
        return '%s%s%s' % (provided_jar.org, '#', provided_jar.name)

      extractors = dict(
          address=lambda target: target.address.spec,
          artifact_id=extract_artifact_id,
          repo_name=lambda target: target.provides.repo.name,
          repo_url=lambda target: target.provides.repo.url,
          repo_db=lambda target: target.provides.repo.push_db,
      )

      def print_provides(column_extractors, target):
        if target.is_exported:
          return ' '.join(extractor(target) for extractor in column_extractors)

      try:
        column_extractors = [extractors[col] for col in (self._provides_columns.split(','))]
      except KeyError:
        raise TaskError('Invalid columns specified %s. Valid ones include address, artifact_id, '
                        'repo_name, repo_url and repo_db.' % self._provides_columns)

      print_fn = lambda target: print_provides(column_extractors, target)
    elif self._documented:
      def print_documented(target):
        if target.description:
          return '%s\n  %s' % (target.address.spec,
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
      return self.context.build_file_parser.scan().targets()
