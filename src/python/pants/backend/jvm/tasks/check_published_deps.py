# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.jar_publish import PushDb


class CheckPublishedDeps(ConsoleTask):

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(CheckPublishedDeps, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag('print-uptodate'), mkflag('print-uptodate', negate=True),
                            dest='check_deps_print_uptodate', default=False,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Also print up-to-date dependencies.')

  def __init__(self, *args, **kwargs):
    super(CheckPublishedDeps, self).__init__(*args, **kwargs)

    self._print_uptodate = self.context.options.check_deps_print_uptodate
    self.repos = self.context.config.getdict('jar-publish', 'repos')
    self._artifacts_to_targets = {}

    def is_published(tgt):
      return tgt.is_exported

    for target in self.context.build_file_parser.scan().targets(predicate=is_published):
      provided_jar, _, _ = target.get_artifact_info()
      artifact = (provided_jar.org, provided_jar.name)
      if not artifact in self._artifacts_to_targets:
        self._artifacts_to_targets[artifact] = target

  def console_output(self, targets):
    push_dbs = {}

    def get_jar_with_version(target):
      db = target.provides.repo.push_db
      if db not in push_dbs:
        push_dbs[db] = PushDb.load(db)
      return push_dbs[db].as_jar_with_version(target)

    visited = set()
    for target in self.context.targets():
      if isinstance(target, (JarLibrary, JvmTarget)):
        for dep in target.jar_dependencies:
          artifact = (dep.org, dep.name)
          if artifact in self._artifacts_to_targets and not artifact in visited:
            visited.add(artifact)
            artifact_target = self._artifacts_to_targets[artifact]
            _, semver, sha, _ = get_jar_with_version(artifact_target)
            if semver.version() != dep.rev:
              yield 'outdated %s#%s %s latest %s' % (dep.org, dep.name, dep.rev, semver.version())
            elif self._print_uptodate:
              yield 'up-to-date %s#%s %s' % (dep.org, dep.name, semver.version())
