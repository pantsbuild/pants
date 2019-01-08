# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.base.specs import Specs
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.legacy.graph import HydratedTargets
from pants.engine.rules import console_rule, optionable_rule
from pants.engine.selectors import Get, Select
from pants.subsystem.subsystem import Subsystem


class ListOptions(Subsystem):
  """Lists all targets matching the target specs.

  If no targets are specified, lists all targets in the workspace.
  """

  # NB: This option scope is temporary: a followup to #6880 will replace the v1 list goal and rename
  # this scope.
  options_scope = 'fastlist'

  @classmethod
  def register_options(cls, register):
    super(ListOptions, cls).register_options(register)
    register('--provides', type=bool,
             help='List only targets that provide an artifact, displaying the columns specified by '
                  '--provides-columns.')
    register('--provides-columns', default='address,artifact_id',
             help='Display these columns when --provides is specified. Available columns are: '
                  'address, artifact_id, repo_name, repo_url, push_db_basedir')
    register('--documented', type=bool,
             help='Print only targets that are documented with a description.')


@console_rule('list', [Select(Console), Select(ListOptions), Select(Specs)])
def fast_list(console, options, specs):
  """A fast variant of `./pants list` with a reduced feature set."""

  provides = options.get_options().provides
  provides_columns = options.get_options().provides_columns
  documented = options.get_options().documented
  if provides or documented:
    # To get provides clauses or documentation, we need hydrated targets.
    collection = yield Get(HydratedTargets, Specs, specs)
    if provides:
      extractors = dict(
          address=lambda target: target.address.spec,
          artifact_id=lambda target: str(target.adaptor.provides),
          repo_name=lambda target: target.adaptor.provides.repo.name,
          repo_url=lambda target: target.adaptor.provides.repo.url,
          push_db_basedir=lambda target: target.adaptor.provides.repo.push_db_basedir,
      )

      def print_provides(column_extractors, target):
        if getattr(target.adaptor, 'provides', None):
          return ' '.join(extractor(target) for extractor in column_extractors)

      try:
        column_extractors = [extractors[col] for col in (provides_columns.split(','))]
      except KeyError:
        raise Exception('Invalid columns specified: {0}. Valid columns are: address, artifact_id, '
                        'repo_name, repo_url, push_db_basedir.'.format(provides_columns))

      print_fn = lambda target: print_provides(column_extractors, target)
    else:
      def print_documented(target):
        description = getattr(target.adaptor, 'description', None)
        if description:
          return '{0}\n  {1}'.format(target.address.spec,
                                     '\n  '.join(description.strip().split('\n')))
      print_fn = print_documented
  else:
    # Otherwise, we can use only addresses.
    collection = yield Get(BuildFileAddresses, Specs, specs)
    print_fn = lambda address: address.spec

  if not collection.dependencies:
    console.print_stderr('WARNING: No targets were matched in goal `{}`.'.format('list'))

  for item in collection:
    result = print_fn(item)
    if result:
      console.print_stdout(result)


def rules():
  return [
      optionable_rule(ListOptions),
      fast_list
    ]
