# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import json
import logging
import os
import pkgutil
import threading
import xml.etree.ElementTree as ET
from abc import abstractmethod
from collections import OrderedDict, defaultdict, namedtuple

import six
from twitter.common.collections import OrderedSet

from pants.backend.jvm.subsystems.jar_dependency_management import (JarDependencyManagement,
                                                                    PinnedJarArtifactSet)
from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.generator import Generator, TemplateData
from pants.base.revision import Revision
from pants.build_graph.target import Target
from pants.ivy.bootstrapper import Bootstrapper
from pants.java.jar.exclude import Exclude
from pants.java.jar.jar_dependency import JarDependency
from pants.java.jar.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.java.util import execute_runner
from pants.util.dirutil import safe_concurrent_creation, safe_mkdir, safe_open
from pants.util.fileutil import atomic_copy

logger = logging.getLogger(__name__)

class JvmResolveError(Exception):
  """An error happened when performing a jvm resolve."""

class ResolutionUtils(object):
  """Common utility functions for doing jvm resolution."""

  class JvmResolveConflictingDepsError(JvmResolveError):
    """Indicates two or more locally declared dependencies conflict."""

  @classmethod
  def calculate_classpath(cls, targets):
    """Creates a consistent classpath and list of excludes for the passed targets.

    It also modifies the JarDependency objects' excludes to contain all the jars excluded by
    provides.

    :param iterable targets: List of targets to collect JarDependencies and excludes from.

    :returns: A pair of a list of JarDependencies, and a set of excludes to apply globally.
    """
    jars = OrderedDict()
    global_excludes = set()
    provide_excludes = set()
    targets_processed = set()

    # Support the ivy force concept when we sanely can for internal dep conflicts.
    # TODO(John Sirois): Consider supporting / implementing the configured ivy revision picking
    # strategy generally.
    def add_jar(jar):
      # TODO(John Sirois): Maven allows for depending on an artifact at one rev and one of its
      # attachments (classified artifacts) at another.  Ivy does not, allow this, the dependency
      # can carry only 1 rev and that hosts multiple artifacts for that rev.  This conflict
      # resolution happens at the classifier level, allowing skew in a
      # multi-artifact/multi-classifier dependency.  We only find out about the skew later in
      # `_generate_jar_template` below which will blow up with a conflict.  Move this logic closer
      # together to get a more clear validate, then emit ivy.xml then resolve flow instead of the
      # spread-out validations happening here.
      # See: https://github.com/pantsbuild/pants/issues/2239
      coordinate = (jar.org, jar.name, jar.classifier)
      existing = jars.get(coordinate)
      jars[coordinate] = jar if not existing else cls._resolve_conflict(existing=existing,
                                                                        proposed=jar)

    def collect_jars(target):
      if isinstance(target, JarLibrary):
        for jar in target.jar_dependencies:
          add_jar(jar)

    def collect_excludes(target):
      target_excludes = target.payload.get_field_value('excludes')
      if target_excludes:
        global_excludes.update(target_excludes)

    def collect_provide_excludes(target):
      if not (isinstance(target, ExportableJvmLibrary) and target.provides):
        return
      logger.debug('Automatically excluding jar {}.{}, which is provided by {}'.format(
        target.provides.org, target.provides.name, target))
      provide_excludes.add(Exclude(org=target.provides.org, name=target.provides.name))

    def collect_elements(target):
      targets_processed.add(target)
      collect_jars(target)
      collect_excludes(target)
      collect_provide_excludes(target)

    for target in targets:
      target.walk(collect_elements, predicate=lambda target: target not in targets_processed)

    # If a source dep is exported (ie, has a provides clause), it should always override
    # remote/binary versions of itself, ie "round trip" dependencies.
    # TODO: Move back to applying provides excludes as target-level excludes when they are no
    # longer global.
    if provide_excludes:
      additional_excludes = tuple(provide_excludes)
      new_jars = OrderedDict()
      for coordinate, jar in jars.items():
        new_jars[coordinate] = jar.copy(excludes=jar.excludes + additional_excludes)
      jars = new_jars

    return jars.values(), global_excludes

  @classmethod
  def _resolve_conflict(cls, existing, proposed):
    if existing.rev is None:
      return proposed
    if proposed.rev is None:
      return existing
    if proposed == existing:
      if proposed.force:
        return proposed
      return existing
    elif existing.force and proposed.force:
      raise cls.JvmResolveConflictingDepsError('Cannot force {}#{};{} to both rev {} and {}'.format(
        proposed.org, proposed.name, proposed.classifier or '', existing.rev, proposed.rev
      ))
    elif existing.force:
      logger.debug('Ignoring rev {} for {}#{};{} already forced to {}'.format(
        proposed.rev, proposed.org, proposed.name, proposed.classifier or '', existing.rev
      ))
      return existing
    elif proposed.force:
      logger.debug('Forcing {}#{};{} from {} to {}'.format(
        proposed.org, proposed.name, proposed.classifier or '', existing.rev, proposed.rev
      ))
      return proposed
    else:
      if Revision.lenient(proposed.rev) > Revision.lenient(existing.rev):
        logger.debug('Upgrading {}#{};{} from rev {}  to {}'.format(
          proposed.org, proposed.name, proposed.classifier or '', existing.rev, proposed.rev,
        ))
        return proposed
      else:
        return existing