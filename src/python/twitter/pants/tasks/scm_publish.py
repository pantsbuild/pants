# ==================================================================================================
# Copyright 2013 Twitter, Inc.
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

from . import Task, TaskError


class Semver(object):
  @staticmethod
  def parse(version):
    components = version.split('.', 3)
    if len(components) != 3:
      raise ValueError
    major, minor, patch = components

    def to_i(component):
      try:
        return int(component)
      except (TypeError, ValueError):
        raise ValueError('Invalid revision component %s in %s - '
                         'must be an integer' % (component, version))
    return Semver(to_i(major), to_i(minor), to_i(patch))

  def __init__(self, major, minor, patch, snapshot=False):
    self.major = major
    self.minor = minor
    self.patch = patch
    self.snapshot = snapshot

  def bump(self):
    # A bump of a snapshot discards snapshot status
    return Semver(self.major, self.minor, self.patch + 1)

  def make_snapshot(self):
    return Semver(self.major, self.minor, self.patch, snapshot=True)

  def version(self):
    return '%s.%s.%s' % (
      self.major,
      self.minor,
      ('%s-SNAPSHOT' % self.patch) if self.snapshot else self.patch
    )

  def __eq__(self, other):
    return self.__cmp__(other) == 0

  def __cmp__(self, other):
    diff = self.major - other.major
    if not diff:
      diff = self.minor - other.minor
      if not diff:
        diff = self.patch - other.patch
        if not diff:
          if self.snapshot and not other.snapshot:
            diff = 1
          elif not self.snapshot and other.snapshot:
            diff = -1
          else:
            diff = 0
    return diff

  def __repr__(self):
    return 'Semver(%s)' % self.version()


class ScmPublish(object):
  def __init__(self, scm, restrict_push_branches):
    self.restrict_push_branches = frozenset(restrict_push_branches or ())
    self.scm = scm

  def check_clean_master(self, commit=False):
    if commit:
      if self.restrict_push_branches:
        branch = self.scm.branch_name
        if branch not in self.restrict_push_branches:
          raise TaskError('Can only push from %s, currently on branch: %s' % (
            ' '.join(sorted(self.restrict_push_branches)), branch
          ))

      changed_files = self.scm.changed_files()
      if changed_files:
        raise TaskError('Can only push from a clean branch, found : %s' % ' '.join(changed_files))
    else:
      print('Skipping check for a clean %s in test mode.' % self.scm.branch_name)

  def commit_push(self, coordinates):
    self.scm.refresh()
    self.scm.commit('pants build committing publish data for push of %s' % coordinates)

