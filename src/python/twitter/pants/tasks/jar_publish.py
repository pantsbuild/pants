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

__author__ = 'John Sirois'

import os
import pkgutil

from twitter.common.config import Properties
from twitter.pants import get_buildroot
from twitter.pants.base.generator import Generator, TemplateData
from twitter.pants.tasks import Task

class JarPublish(Task):
  def __init__(self, context):
    Task.__init__(self, context)

  def execute(self, targets):
    self.context.log.warn('TODO(John Sirois): implement')


class Semver(object):
  @staticmethod
  def parse(version):
    components = version.split('.', 3)
    if len(components) != 3:
      raise ValueError
    major, minor, patch = components
    return Semver(major, minor, patch)

  def __init__(self, major, minor, patch):
    self.major = int(major)
    self.minor = int(minor)
    self.patch = int(patch)

  def bump(self):
    self.patch += 1

  def version(self):
    return '%s.%s.%s' % (self.major, self.minor, self.patch)

  def __eq__(self, other):
    return self.__cmp__(other) == 0

  def __cmp__(self, other):
    diff = self.major - other.major
    if not diff:
      diff = self.major - other.major
      if not diff:
        diff = self.patch - other.patch
    return diff

  def __repr__(self):
    return 'Semver(%s)' % self.version()


class PushDb(object):
  @staticmethod
  def load(file):
    """Loads a pushdb maintained in a properties file at the given path."""
    with open(file, 'r') as props:
      properties = Properties.load(props)
      return PushDb(properties)

  def __init__(self, props):
    self._props = props

  def as_jar_with_version(self, target):
    """Given an internal target, return a JarDependency with the last published revision filled
    in."""
    jar_dep, db_get, _ = self._accessors_for_target(target)

    major = db_get('revision.major', '0')
    minor = db_get('revision.minor', '0')
    patch = db_get('revision.patch', '0')
    jar_dep.rev = Semver(major, minor, patch).version()
    return jar_dep

  def set_version(self, target, version):
    version = Semver.parse(version)
    _, _, db_set = self._accessors_for_target(target)
    db_set('revision.major', version.major)
    db_set('revision.minor', version.minor)
    db_set('revision.patch', version.patch)

  def _accessors_for_target(self, target):
    jar_dep, id, exported = target._get_artifact_info()
    if not exported:
      raise ValueError

    def key(prefix):
      '%s.%s%%%s' % (prefix, jar_dep.org, jar_dep.name)

    def getter(prefix, default=None):
      return self._props.get(key(prefix), default)

    def setter(prefix, value):
      self._props[key(prefix)] = value

    return jar_dep, getter, setter

  def dump(self, file):
    """Saves the pushdb as a properties file to the given path."""
    with open(file, 'w+a') as props:
      Properties.dump(self._props, props)


class PomWriter(object):
  @staticmethod
  def jardep(jar, excludes=True):
    def create_exclude(exclude):
      return TemplateData(
        org=exclude.org,
        name=exclude.name,
      )
    template_data = TemplateData(
      org=jar.org,
      name=jar.name,
      rev=jar.rev,
    )
    if excludes and jar.excludes:
      template_data = template_data.extend(
        excludes=[create_exclude(exclude) for exclude in jar.excludes if exclude.name]
      )
    return template_data

  def __init__(self, pushdb):
    self.pushdb = pushdb

  def write(self, target, path):
    dependencies = [self.internaldep(dep) for dep in target.internal_dependencies]
    dependencies.extend(PomWriter.jardep(dep) for dep in target.jar_dependencies if dep.rev)
    template_data = self.internaldep(target).extend(
      dependencies=dependencies
    )

    pomname = '%s-%s.pom' % (target_jar.name, target_jar.rev)
    with open(os.path.join(path, pomname), 'w+a') as output:
      generator = Generator(pkgutil.get_data(__name__, os.path.join('jar_publish', 'pom.mk')),
                            root_dir = get_buildroot(),
                            artifact = template_data)
      generator.write(output)

  def internaldep(target, excludes=True):
    jar = self.pushdb.as_jar_with_version(target)
    return PomWriter.jardep(jar, excludes)

