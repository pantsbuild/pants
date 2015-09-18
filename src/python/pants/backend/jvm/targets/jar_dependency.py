# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.exclude import Exclude
from pants.base.build_manual import manual
from pants.base.deprecated import deprecated
from pants.base.payload_field import PayloadField, stable_json_sha1
from pants.base.validation import assert_list


# TODO(Eric Ayers) There are two classes named IvyArtifact, the one and one in ivy_utils.py
# This one needs to go when we refactor Ivy datastructures out of the rest of pants.
class IvyArtifact(PayloadField):
  """
  Specification for an Ivy Artifact for this jar dependency.

  See: http://ant.apache.org/ivy/history/latest-milestone/ivyfile/artifact.html
  """

  _HASH_KEYS = (
    'name',
    'type_',
    'ext',
    'conf',
    'url',
    'classifier',
  )

  def __init__(self, name, type_=None, ext=None, conf=None, url=None, classifier=None):
    """Declares a dependency on an artifact to be resolved externally.

    :param name: The name of the published artifact. This name must not include revision.
    :param type_: The type of the published artifact. It's usually the same as the artifact's file
      extension, but not necessarily. For instance, ivy files are of type 'ivy' but have 'xml' as
      their file extension.
    :param ext: The file extension of the published artifact.
    :param url: The url at which this artifact can be found if it isn't located at the standard
      location in the repository.
    :param configuration: The public configuration in which this artifact is published. The '*' wildcard can
      be used to designate all public configurations.
    :param classifier: The maven classifier of this artifact.
    """
    self.name = name
    self.type_ = type_ or 'jar'
    self.ext = ext
    self.conf = conf
    self.url = url
    self.classifier = classifier

  def _compute_fingerprint(self):
    return stable_json_sha1(dict(name=self.name,
                                 type_=self.type_,
                                 ext=self.ext,
                                 conf=self.conf,
                                 url=self.url,
                                 classifier=self.classifier))

  def cache_key(self):
    return ''.join(str(getattr(self, key)) for key in self._HASH_KEYS)

  def __repr__(self):
    return ('IvyArtifact({!r}, type_={!r}, ext={!r}, conf={!r}, url={!r}, classifier={!r})'
            .format(self.name, self.type_, self.ext, self.conf, self.url, self.classifier))


class JarDependency(object):
  """A pre-built Maven repository dependency."""

  _HASH_KEYS = (
    'org',
    'name',
    'rev',
    'classifier',
    'force',
    'excludes',
    'transitive',
    'mutable',
  )

  def __init__(self, org, name, rev=None, force=False, ext=None, url=None, apidocs=None,
               type_=None, classifier=None, mutable=None, artifacts=None, intransitive=False):
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
    :param string type_: Artifact packaging type.
    :param string classifier: Classifier specifying the artifact variant to use.
    :param boolean mutable: Inhibit caching of this mutable artifact. A common use is for
      Maven -SNAPSHOT style artifacts in an active development/integration cycle.
    :param list artifacts: A list of additional IvyArtifacts
    :param boolean intransitive: Declares this Dependency intransitive, indicating only the jar for
    the dependency itself should be downloaded and placed on the classpath
    """
    self.org = org
    self.name = name
    self.rev = rev
    self.force = force
    self.excludes = tuple()
    self.transitive = not intransitive
    self.apidocs = apidocs
    self.mutable = mutable

    @deprecated(removal_version='0.0.49',
                hint_message='JarDependency now only specifies a single artifact, so the '
                             'artifacts argument will be removed.')
    def make_artifacts():
      return tuple(assert_list(artifacts, expected_type=IvyArtifact, key_arg='artifacts'))

    if artifacts:
      self.artifacts = make_artifacts()
    else:
      self.artifacts = ()

    if ext or url or type_ or classifier:
      self.append_artifact(name,
                           type_=type_,
                           ext=ext,
                           url=url,
                           classifier=classifier)

    self._configurations = ('default',)

    if classifier:
      self.classifier = classifier
    elif len(self.artifacts) == 1:
      self.classifier = self.artifacts[0].classifier
    else:
      self.classifier = None

    self._coordinates = (self.org, self.name, self.rev)
    if self.classifier:
      self._coordinates += (self.classifier,)

    if not self.classifier and len(self.artifacts) > 1:
      raise ValueError('Cannot determine classifier. No explicit classifier is set and this jar '
                       'has more than 1 artifact: {}\n\t{}'.format(self, '\n\t'.join(map(str, self.artifacts))))

  def append_artifact(self, name, type_=None, ext=None, conf=None, url=None, classifier=None):
    """Append a new IvyArtifact to the list of artifacts for this jar."""

    @deprecated(removal_version='0.0.49',
                hint_message='JarDependency now only specifies a single artifact, {} defines more '
                             'than one.'.format(name))
    def add_more_artifacts():
      return self.artifacts + (IvyArtifact(name, type_=type_, ext=ext, conf=conf, url=url, classifier=classifier), )
    if self.artifacts:
      self.artifacts = add_more_artifacts()
    else:
      self.artifacts = (IvyArtifact(name, type_=type_, ext=ext, conf=conf, url=url, classifier=classifier), )

  @manual.builddict()
  def exclude(self, org, name=None):
    """Adds a transitive dependency of this jar to the exclude list."""

    self.excludes += (Exclude(org, name),)
    return self

  def __eq__(self, other):
    return self._coordinates == other._coordinates

  def __hash__(self):
    return hash(self._coordinates)

  def __lt__(self, other):
    return self._coordinates < other._coordinates

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return self.id

  @property
  def id(self):
    return "-".join(map(str, self._coordinates))

  @property
  def coordinate_without_rev(self):
    return (self.org, self.name, self.classifier)

  @property
  def artifact_classifiers(self):
    if self.artifacts:
      return {a.classifier for a in self.artifacts}
    else:
      # If there are no artifacts, there's one implicit artifact with the
      # classifier None.
      return {None}

  def cache_key(self):
    key = ''.join(str(getattr(self, key)) for key in self._HASH_KEYS)
    key += ''.join(sorted(self._configurations))
    key += ''.join(a.cache_key() for a in sorted(self.artifacts, key=lambda a: a.name + a.type_))
    return key
