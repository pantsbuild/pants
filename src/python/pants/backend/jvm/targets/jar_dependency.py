# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.jar_dependency_utils import M2Coordinate
from pants.backend.jvm.targets.exclude import Exclude
from pants.base.payload_field import stable_json_sha1
from pants.base.validation import assert_list
from pants.util.memo import memoized_property
from pants.util.objects import datatype


class JarDependency(datatype('JarDependency', [
  'org', 'base_name', 'rev', 'force', 'ext', 'url', 'apidocs',
  'classifier', 'mutable', 'intransitive', 'excludes'])):
  """A pre-built Maven repository dependency.

  :API: public
  """

  @staticmethod
  def _prepare_excludes(excludes):
    return tuple(assert_list(excludes,
                             expected_type=Exclude,
                             can_be_none=True,
                             key_arg='excludes',
                             allowable=(tuple, list,)))

  def __new__(cls, org, name, rev=None, force=False, ext=None, url=None, apidocs=None,
              classifier=None, mutable=None, intransitive=False, excludes=None):
    """
    :param string org: The Maven ``groupId`` of this dependency.
    :param string name: The Maven ``artifactId`` of this dependency.
    :param string rev: The Maven ``version`` of this dependency.
      If unspecified the latest available version is used.
    :param boolean force: Force this specific artifact revision even if other transitive
      dependencies specify a different revision. This requires specifying the ``rev`` parameter.
    :param string ext: Extension of the artifact if different from the artifact type.
      This is sometimes needed for artifacts packaged with Maven bundle type but stored as jars.
    :param string url: URL of this artifact, if different from the Maven repo standard location
      (specifying this parameter is unusual).
    :param string apidocs: URL of existing javadocs, which if specified, pants-generated javadocs
      will properly hyperlink {\ @link}s.
    :param string classifier: Classifier specifying the artifact variant to use.
    :param boolean mutable: Inhibit caching of this mutable artifact. A common use is for
      Maven -SNAPSHOT style artifacts in an active development/integration cycle.
    :param boolean intransitive: Declares this Dependency intransitive, indicating only the jar for
      the dependency itself should be downloaded and placed on the classpath
    :param list excludes: Transitive dependencies of this jar to exclude.
    :type excludes: list of :class:`pants.backend.jvm.targets.exclude.Exclude`
    """
    excludes = JarDependency._prepare_excludes(excludes)
    return super(JarDependency, cls).__new__(
        cls, org=org, base_name=name, rev=rev, force=force, ext=ext, url=url, apidocs=apidocs,
        classifier=classifier, mutable=mutable, intransitive=intransitive, excludes=excludes)

  @property
  def name(self):
    return self.base_name

  @property
  def transitive(self):
    return not self.intransitive

  def copy(self, **replacements):
    """Returns a clone of this JarDependency with the given replacements kwargs overlaid."""
    cls = type(self)
    kwargs = self._asdict()
    for key, val in replacements.items():
      if key == 'excludes':
        val = JarDependency._prepare_excludes(val)
      kwargs[key] = val
    org = kwargs.pop('org')
    base_name = kwargs.pop('base_name')
    return cls(org, base_name, **kwargs)

  def __str__(self):
    return 'JarDependency({})'.format(self.coordinate)

  @memoized_property
  def coordinate(self):
    """Returns the maven coordinate of this jar.

    :rtype: :class:`pants.backend.jvm.jar_dependency_utils.M2Coordinate`
    """
    return M2Coordinate(org=self.org, name=self.name, rev=self.rev, classifier=self.classifier,
                        ext=self.ext)

  def cache_key(self):
    excludes = [(e.org, e.name) for e in self.excludes]
    return stable_json_sha1(dict(org=self.org,
                                 name=self.name,
                                 rev=self.rev,
                                 force=self.force,
                                 ext=self.ext,
                                 url=self.url,
                                 classifier=self.classifier,
                                 transitive=self.transitive,
                                 mutable=self.mutable,
                                 excludes=excludes,))
