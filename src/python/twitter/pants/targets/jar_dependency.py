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

from twitter.pants.base.generator import TemplateData
from twitter.pants.targets.exclude import Exclude

class JarDependency(object):
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
  """

  def __init__(self, org, name, rev = None, force = False, ext = None, url = None, apidocs = None):
    self.org = org
    self.name = name
    self.rev = rev
    self.force = force
    self.excludes = []
    self.transitive = True
    self.ext = ext
    self.url = url
    self.apidocs = apidocs
    self.id = None
    self._configurations = [ 'default' ]

    # Support legacy method names
    # TODO(John Sirois): introduce a deprecation cycle for these and then kill
    self.withSources = self.with_sources
    self.withDocs = self.with_sources

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

  def __eq__(self, other):
    result = other and (
      type(other) == JarDependency) and (
      self.org == other.org) and (
      self.name == other.name) and (
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
    return "%s-%s-%s" % (self.org, self.name, self.rev)

  def resolve(self):
    yield self

  def _as_jar_dependencies(self):
    yield self

  def _create_template_data(self):
    return TemplateData(
      org = self.org,
      module = self.name,
      version = self.rev,
      force = self.force,
      excludes = self.excludes,
      transitive = self.transitive,
      ext = self.ext,
      url = self.url,
      configurations = ';'.join(self._configurations),
    )
