# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import urlparse

from pants.base.build_environment import get_buildroot
from pants.base.payload_field import stable_json_sha1
from pants.base.validation import assert_list
from pants.java.jar.exclude import Exclude
from pants.java.jar.jar_dependency_utils import M2Coordinate
from pants.util.memo import memoized_method, memoized_property
from pants.util.objects import datatype


class JarDependencyParseContextWrapper(object):
  """A pre-built Maven repository dependency.

  Examples:

    # The typical use case.
    jar('com.puppycrawl.tools', 'checkstyle', '1.2')

    # Test external dependency locally.
    jar('org.foobar', 'foobar', '1.2-SNAPSHOT',
        url='file:///Users/pantsdev/workspace/project/jars/checkstyle/checkstyle.jar')

    # Test external dependency locally using relative path (with respect to the path
    # of the belonging BUILD file)
    jar('org.foobar', 'foobar', '1.2-SNAPSHOT',
        url='file:../checkstyle/checkstyle.jar')
  """

  def __init__(self, parse_context):
    """
    :param parse_context: The BUILD file parse context.
    """
    self._parse_context = parse_context

  def __call__(self, org, name, rev=None, force=False, ext=None, url=None, apidocs=None,
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
      (specifying this parameter is unusual). Path of file URL can be either absolute or relative
      to the belonging BUILD file.
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
    return JarDependency(org, name, rev, force, ext, url, apidocs, classifier, mutable, intransitive,
                         excludes, self._parse_context.rel_path)


class JarDependency(datatype('JarDependency', [
  'org', 'base_name', 'rev', 'force', 'ext', 'url', 'apidocs',
  'classifier', 'mutable', 'intransitive', 'excludes', 'base_path'])):
  """A pre-built Maven repository dependency.

  This is the developer facing api, compared to the context wrapper class
  `JarDependencyParseContextWrapper`, which exposes api through build file to users.

  The only additional parameter `base_path` here is so that we can retrieve the file URL
  in its absolute (for ivy) or relative (for fingerprinting) form. The context wrapper class
  determines the `base_path` from where `jar` is defined at.

  If a relative file url is provided, its absolute form will be (`buildroot` + `base_path` + relative url).

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
              classifier=None, mutable=None, intransitive=False, excludes=None, base_path=None):
    """

    :param string base_path: base path that's relative to the build root.
    """
    excludes = JarDependency._prepare_excludes(excludes)
    base_path = base_path or '.'
    if os.path.isabs(base_path):
      base_path = os.path.relpath(base_path, get_buildroot())
    return super(JarDependency, cls).__new__(
        cls, org=org, base_name=name, rev=rev, force=force, ext=ext, url=url, apidocs=apidocs,
        classifier=classifier, mutable=mutable, intransitive=intransitive, excludes=excludes,
        base_path=base_path)

  @property
  def name(self):
    return self.base_name

  @memoized_method
  def get_url(self, relative=False):
    if self.url:
      parsed_url = urlparse.urlparse(self.url)
      if parsed_url.scheme == 'file':
        if relative and os.path.isabs(parsed_url.path):
          relative_path = os.path.relpath(parsed_url.path,
                                          os.path.join(get_buildroot(), self.base_path))
          return 'file:{path}'.format(path=os.path.normpath(relative_path))
        if not relative and not os.path.isabs(parsed_url.path):
          abs_path = os.path.join(get_buildroot(), self.base_path, parsed_url.path)
          return 'file://{path}'.format(path=os.path.normpath(abs_path))
    return self.url

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

    :rtype: :class:`pants.java.jar.M2Coordinate`
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
                                 url=self.get_url(relative=True),
                                 classifier=self.classifier,
                                 transitive=self.transitive,
                                 mutable=self.mutable,
                                 excludes=excludes,))
