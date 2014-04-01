# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_manual import manual
from pants.targets.jvm_target import JvmTarget
from pants.targets.resources import WithResources


@manual.builddict(tags=['jvm'])
class JavaTests(JvmTarget, WithResources):
  """Tests JVM sources with JUnit."""

  def __init__(self,
               name,
               sources=None,
               dependencies=None,
               excludes=None,
               resources=None,
               exclusives=None):
    """
   :param string name: The name of this target, which combined with this
     build file defines the target :class:`pants.base.address.Address`.
   :param sources: A list of filenames representing the source code
     this library is compiled from.
   :type sources: list of strings
   :param Artifact provides:
     The :class:`pants.targets.artifact.Artifact`
     to publish that represents this target outside the repo.
   :param dependencies: List of :class:`pants.base.target.Target` instances
     this target depends on.
   :type dependencies: list of targets
   :param excludes: List of :class:`pants.targets.exclude.Exclude` instances
     to filter this target's transitive dependencies against.
   :param resources: An optional list of ``resources`` targets containing text
     file resources to place in this module's jar.
   :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
   """
    super(JavaTests, self).__init__(name, sources, dependencies, excludes, exclusives=exclusives)

    self.resources = resources

    # TODO(John Sirois): These could be scala, clojure, etc.  'jvm' and 'tests' are the only truly
    # applicable labels - fixup the 'java' misnomer.
    self.add_labels('java', 'tests')
