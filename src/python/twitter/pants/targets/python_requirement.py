# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pkg_resources import Requirement

from pants.base.build_manual import manual
from pants.base.target import Target
from pants.targets.external_dependency import ExternalDependency


@manual.builddict(tags=["python"])
class PythonRequirement(Target, ExternalDependency):
  """Pants wrapper around pkg_resources.Requirement"""

  def __init__(self, requirement, name=None, repository=None, version_filter=None, use_2to3=False,
               compatibility=None, exclusives=None):
    # TODO(wickman) Allow PythonRequirements to be specified using pip-style vcs or url identifiers,
    # e.g. git+https or just http://...
    self._requirement = Requirement.parse(requirement)
    self._repository = repository
    self._name = name or self._requirement.project_name
    self._use_2to3 = use_2to3
    self._version_filter = version_filter or (lambda py, pl: True)
    # TODO(wickman) Unify this with PythonTarget .compatibility
    self.compatibility = compatibility or ['']
    Target.__init__(self, self._name, exclusives=exclusives)

  def should_build(self, python, platform):
    return self._version_filter(python, platform)

  @property
  def use_2to3(self):
    return self._use_2to3

  @property
  def repository(self):
    return self._repository

  # duck-typing Requirement interface for Resolver, since Requirement cannot be
  # subclassed (curses!)
  @property
  def key(self):
    return self._requirement.key

  @property
  def extras(self):
    return self._requirement.extras

  @property
  def specs(self):
    return self._requirement.specs

  @property
  def project_name(self):
    return self._requirement.project_name

  @property
  def requirement(self):
    return self._requirement

  def __contains__(self, item):
    return item in self._requirement

  def cache_key(self):
    return str(self._requirement)

  def __repr__(self):
    return 'PythonRequirement(%s)' % self._requirement
