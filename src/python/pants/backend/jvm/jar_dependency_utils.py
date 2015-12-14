# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.memo import memoized_property


class ResolvedJar(object):
  """Represents an artifact resolved from the dependency resolution process."""

  def __init__(self, coordinate, cache_path, pants_path=None):
    """
    :param coordinate: Coordinate representing this resolved jar.
    :type coordinate: :class:`M2Coordinate`
    :param string cache_path: Path to the artifact in the ivy cache
    :param string pants_path: Path to the symlink for the artifact in the pants work directory.
    """
    self.coordinate = coordinate
    self.cache_path = cache_path
    self.pants_path = pants_path

    self._id = (coordinate, cache_path, pants_path)

  def __eq__(self, other):
    return isinstance(other, ResolvedJar) and self._id == other._id

  def __ne__(self, other):
    return not self == other

  def __hash__(self):
    return hash(self._id)

  def __repr__(self):
    return 'ResolvedJar(coordinate={!r}, cache_path={!r}, pants_path={!r})'.format(*self._id)


class M2Coordinate(object):
  """Represents a fully qualified name of an artifact."""

  def __init__(self, org, name, rev=None, classifier=None, ext=None):
    """
    :param string org: The maven dependency `groupId`.
    :param string name: The maven dependency `artifactId`.
    :param string rev: The maven dependency `version`.
    :param string classifier: The maven dependency `classifier`.
    :param string ext: There is no direct maven parallel, but the maven `packaging` value of the
                       depended-on artifact for simple cases, and in more complex cases the
                       extension of the artifact.  For example, 'bundle' packaging implies an
                       extension of 'jar'.  Defaults to 'jar'.
    """
    self.org = org
    self.name = name
    self.rev = rev
    self.classifier = classifier
    self.ext = ext or 'jar'

    self._id = (self.org, self.name, self.rev, self.classifier, self.ext)

  @memoized_property
  def artifact_filename(self):
    """Returns the canonical maven-style filename for an artifact pointed at by this coordinate.

    :rtype: string
    """
    def maybe_compenent(component):
      return '-{}'.format(component) if component else ''

    return '{org}-{name}{rev}{classifier}.{ext}'.format(org=self.org,
                                                        name=self.name,
                                                        rev=maybe_compenent(self.rev),
                                                        classifier=maybe_compenent(self.classifier),
                                                        ext=self.ext)

  def __eq__(self, other):
    return isinstance(other, M2Coordinate) and self._id == other._id

  def __ne__(self, other):
    return not self == other

  def __hash__(self):
    return hash(self._id)

  def __str__(self):
    # Doesn't follow https://maven.apache.org/pom.html#Maven_Coordinates
    # Instead produces an unambiguous string representation of the coordinate
    # org:name:rev:classifier:type_
    # if any of the fields are None, it uses ''
    # for example org=a, name=b, type_=jar -> a:b:::jar
    return ':'.join((x or '') for x in self._id)

  def __repr__(self):
    return ('M2Coordinate(org={!r}, name={!r}, rev={!r}, classifier={!r}, ext={!r})'
            .format(*self._id))
