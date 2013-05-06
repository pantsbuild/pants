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

import glob
import hashlib
import os

from twitter.common.dirutil import safe_mkdir, safe_delete

from twitter.pants import Config, TaskError
from twitter.pants.java import SubprocessExecutor

from .ivy import Bootstrapper, Ivy


def profile_classpath(profile, java_executor=None, config=None):
  """Loads the given profile's classpath if necessary and returns a tuple of
  (updated: bool, classpath: [string]).

  :param string profile: Name of a jvm tool profile.
  :param java_executor: An optional java executor.
  :type java_executor: :class:`twitter.pants.java.Executor`
  :param config: An optional site config.
  :type config: :class:`twitter.pants.base.Config`
  :param string ivy_jar: Optional path to a self-contained ivy jar.
  :param string ivy_settings: Optional path to an ivysettings.xml file.
  """
  # TODO(John Sirois): rework profiles to use the IvyResolve infrastructure used for all other
  # classpath resolution needs.

  # The mechanism used is to store the resolved classpath in a *.checked file whose name contains
  # the hash of the ivy file contents.  In the fast path this allows obtaining the previously
  # resolved classpath by hashing the ivy file, and reading the *.checked file that suggests for
  # the classpath contained within.  When the *.checked for the hash does not exist, this implies
  # the ivy file changed and we need to re-resolve.  In this slow-path case we clean up all the
  # old *.checked files for this profile.

  config = config or Config.load()
  profile_dir = config.get('ivy-profiles', 'workdir')
  ivy_xml = os.path.join(profile_dir, '%s.ivy.xml' % profile)
  if not os.path.exists(ivy_xml):
    raise TaskError('The ivy.xml to configure the %s tool classpath at %s '
                    'is missing.' % (profile, ivy_xml))

  digest = hashlib.sha1()
  with open(ivy_xml) as fp:
    digest.update(fp.read())

  profile_libdir = os.path.join(profile_dir, '%s.libs' % profile)
  profile_check = '%s.%s.checked' % (profile_libdir, digest.hexdigest())
  updated = False
  if not os.path.exists(profile_check):
    safe_mkdir(profile_libdir, clean=True)
    for path in glob.glob('%s*.checked' % profile_libdir):
      safe_delete(path)

    java_executor = java_executor or SubprocessExecutor()
    try:
      ivy = Bootstrapper.default_ivy(java_executor)
      ivy.execute([
        '-ivy', ivy_xml,

        # TODO(John Sirois): this pattern omits an [organisation]- prefix to satisfy IDEA jar naming
        # needs for scala - isolate this hack to idea.py where it belongs
        '-retrieve', '%s/[artifact]-[revision](-[classifier]).[ext]' % profile_libdir,

        # TODO(John Sirois): just use -cachepath and let ivy generate the classpath file contents
        # directly

        '-symlink',
        '-types', 'jar', 'bundle',
        '-confs', 'default'
      ])
    except (Bootstrapper.Error, Ivy.Error) as e:
      raise TaskError('Failed to load profile %s! %s' % (profile_check, e))

    with open(profile_check, 'w') as cp:
      for jar in os.listdir(profile_libdir):
        cp.write('%s\n' % os.path.join(profile_libdir, jar))
    updated = True

  with open(profile_check) as cp:
    return updated, map(lambda entry: entry.strip(), cp.readlines())
