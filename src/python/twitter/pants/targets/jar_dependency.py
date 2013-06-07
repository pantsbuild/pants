# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

from collections import defaultdict
from twitter.pants.targets.exclude import Exclude
from collections import defaultdict

from .external_dependency import ExternalDependency


class Artifact(object):
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

  def __init__(self, name, type_, ext=None, conf=None, url=None, classifier=None):
    """Initializes a new artifact specification.

    name:       The name of the published artifact. This name must not include revision.
    type_:      The type of the published artifact. It's usually its extension, but not necessarily.
                For instance, ivy files are of type 'ivy' but have 'xml' extension.
    ext:        The extension of the published artifact.
    conf:       The public configuration in which this artifact is published. The '*' wildcard can
                be used to designate all public configurations.
    url:        The url at which this artifact can be found if it isn't located at the standard
                location in the repository
    classifier: The maven classifier of this artifact.
    """
    self.name = name
    self.type_ = type_
    self.ext = ext
    self.conf = conf
    self.url = url
    self.classifier = classifier

  def cache_key(self):
    return ''.join(str(getattr(self, key)) for key in self._HASH_KEYS)


class  JarDependency(ExternalDependency):
  """Represents a binary jar dependency ala maven or ivy.  For the ivy dependency defined by:
    <dependency org="com.google.guava" name="guava" rev="r07"/>

  The equivalent Dependency object could be created with:
    JarDependency(org = "com.google.guava", name = "guava", rev = "r07")

  If the rev keyword argument is left out, the revision is assumed to be the latest available.

  If the rev is specified and force = True is also specified, this will force the artifact revision
  to be rev even if other transitive deps specify a different revision for the same artifact.

  The extension of the artifact can be over-ridden if it differs from the artifact type with the ext
  keyword argument.  This is sometimes needed for artifacts packaged with maven bundle type but
  stored as jars.

  The url of the artifact can be over-ridden if non-standard by specifying the url keyword argument.

  If the dependency has API docs available online, these can be noted with apidocs and generated
  javadocs with {@link}s to the jar's classes will be properly hyperlinked.

  If the dependency is mutable this must be explicitly noted.  A common use-case is to inhibit
  caching of maven -SNAPSHOT style artifacts in an active development/integration cycle.

  If you want to use a maven classifier variant of a jar, use the classifier param. If you want
  to include multiple artifacts with differing classifiers, use with_artifact.
  """

  _HASH_KEYS = (
    'org',
    'name',
    'rev',
    'force',
    'excludes',
    'transitive',
    'mutable',
  )

  def __init__(self, org, name, rev=None, force=False, ext=None, url=None, apidocs=None,
               type_=None, classifier=None, mutable=None, exclusives=None):
    self.org = org
    self.name = name
    self.rev = rev
    self.force = force
    self.excludes = []
    self.transitive = True
    self.apidocs = apidocs
    self.mutable = mutable

    self.artifacts = []
    if ext or url or type_ or classifier:
      self.with_artifact(name=name, type_=type_, ext=ext, url=url, classifier=classifier)

    self.id = "%s-%s-%s" % (self.org, self.name, self.rev)
    self._configurations = ['default']
    self.declared_exclusives = defaultdict(set)
    if exclusives is not None:
      for k in exclusives:
        self.declared_exclusives[k] |= exclusives[k]

    # Support legacy method names
    # TODO(John Sirois): introduce a deprecation cycle for these and then kill
    self.withSources = self.with_sources
    self.withDocs = self.with_sources

    # Legacy variables needed by ivy jar publish
    self.ext = ext
    self.url = url

    self.declared_exclusives = defaultdict(set)
    if exclusives is not None:
      for k in exclusives:
        self.declared_exclusives[k] |= exclusives[k]


  def exclude(self, org, name = None):
    """Adds a transitive dependency of this jar to the exclude list."""

    self.excludes.append(Exclude(org, name))
    return self

  def intransitive(self):
    """Declares this Dependency intransitive, indicating only the jar for the dependency itself
    should be downloaded and placed on the classpath"""

    self.transitive = False
    return self

  def with_sources(self):
    self._configurations.append('sources')
    return self

  def with_docs(self):
    self._configurations.append('docs')
    return self

  # TODO: This is necessary duck-typing because in some places JarDependency is treated like
  # a Target, even though it doesn't extend Target. Probably best to fix that.
  def has_label(self, label):
    return False

  def with_artifact(self, name=None, type_=None, ext=None, url=None, configuration=None,
                    classifier=None):
    """Sets an alternative artifact to fetch or adds additional artifacts if called multiple times.
    """
    artifact = Artifact(name or self.name, type_ or 'jar', ext=ext, url=url, conf=configuration,
                        classifier=classifier)
    self.artifacts.append(artifact)
    return self

  # TODO: This is necessary duck-typing because in some places JarDependency is treated like
  # a Target, even though it doesn't extend Target. Probably best to fix that.
  def has_label(self, label):
    return False

  def __eq__(self, other):
    result = (isinstance(other, type(self)) and
              self.org == other.org and
              self.name == other.name and
              self.rev == other.rev)
    return result

  def __hash__(self):
    value = 17
    value *= 37 + hash(self.org)
    value *= 37 + hash(self.name)
    value *= 37 + hash(self.rev)
    return value

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return self.id

  def cache_key(self):
    key = ''.join(str(getattr(self, key)) for key in self._HASH_KEYS)
    key += ''.join(sorted(self._configurations))
    key += ''.join(a.cache_key() for a in sorted(self.artifacts, key=lambda a: a.name + a.type_))
    return key

  def resolve(self):
    yield self

  def walk(self, work, predicate = None):
    if not predicate or predicate(self):
      work(self)

  def _as_jar_dependencies(self):
    yield self
