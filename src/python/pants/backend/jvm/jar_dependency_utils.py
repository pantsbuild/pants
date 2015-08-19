# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class ResolvedJar(object):
  """Output from the resolve process."""

  def __init__(self, coordinate, cache_path, path=None):
    """
    :param M2Coordinate coordinate: Coordinate representing this resolved jar.
    :param string cache_path: Path to the artifact in the ivy cache
    :param string path: Path to the symlink for the artifact in the pants work directory.
    """
    self.coordinate = coordinate
    self.cache_path = cache_path
    self.path = path

  def __eq__(self, other):
    return self.coordinate == other.coordinate and \
           self.cache_path == other.cache_path and \
           self.path == other.path

  def __ne__(self, other):
    return not self == other

  def __hash__(self):
    return hash((self.coordinate, self.cache_path, self.path))


class M2Coordinate(object):
  """Represents a fully qualified name of an artifact in a M2 repository."""

  def __init__(self, org, name, rev=None, classifier=None, type_='jar'):
    """
    :param org: Maven equivalent of orgId
    :param name: Maven equivalent of groupId
    :param type_: Maven equivalent of packaging. Defaults to jar.
    :param classifier: Maven equivalent of classifier.
    :param rev: Version of the artifact.
    """
    self.org = org
    self.name = name
    self.type_ = type_
    self.rev = rev
    self.classifier = classifier

    self._id = (org, name, rev, classifier, type_)

  def __eq__(self, other):
    return self._id == other._id

  def __ne__(self, other):
    return self._id != other._id

  def __hash__(self):
    return hash(self._id)

  def __str__(self):
    # Doesn't follow https://maven.apache.org/pom.html#Maven_Coordinates
    # Instead produces an unambiguous string representation of the coordinate
    # org:name:rev:classifier:type_
    # if any of the fields are None, it uses ''
    # for example org=a, name=b, type_=jar -> a:b:::jar
    return ':'.join(x or '' for x in self._id)
