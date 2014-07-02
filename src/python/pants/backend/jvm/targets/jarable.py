# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractproperty

from twitter.common.lang import AbstractClass

from pants.backend.jvm.targets.jar_dependency import JarDependency


class Jarable(AbstractClass):
  """A mixin that identifies a target as one that can provide a jar."""

  @abstractproperty
  def identifier(self):
    """Subclasses should return a stable unique identifier for the jarable target."""

  @property
  def provides(self):
    """Returns an optional :class:`pants.backend.jvm.targets.artifact.Artifact` if this target is exportable.

    Subclasses should override to provide an artifact descriptor when one applies, by default None
    is supplied.
    """
    return None

  def get_artifact_info(self):
    """Returns a triple composed of a :class:`pants.backend.jvm.targets.jar_dependency.JarDependency`
    describing the jar for this target, this target's artifact identifier and a bool indicating if
    this target is exportable.
    """
    exported = bool(self.provides)

    org = self.provides.org if exported else 'internal'
    module = self.provides.name if exported else self.identifier

    id_ = "%s-%s" % (self.provides.org, self.provides.name) if exported else self.identifier

    # TODO(John Sirois): This should return something less than a JarDependency encapsulating just
    # the org and name.  Perhaps a JarFamily?
    return JarDependency(org=org, name=module, rev=None), id_, exported
