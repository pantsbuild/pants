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

import getpass
import os
import subprocess

from twitter.common.config import Properties
from twitter.common.dirutil import safe_mkdir
from twitter.pants.targets import RubyThriftLibrary
from twitter.pants.tasks.scm_publish import ScmPublish, Semver
from twitter.pants import get_scm
from . import Task, TaskError


def is_ruby_library(target):
  return isinstance(target, RubyThriftLibrary)


class PushDb(object):
  @staticmethod
  def load(path):
    """Loads a pushdb maintained in a properties file at the given path."""
    with open(path, 'r') as props:
      properties = Properties.load(props)
      return PushDb(properties)

  def __init__(self, props):
    self._props = props

  def next_version(self, target):
    """
      Given an internal target, return a JarDependency with the last published revision filled in.
    """
    return Semver.parse(self._props.get(target.provides.name) or "0.0.0").bump().version()

  def set_version(self, target, version):
    self._props[target.provides.name] = version

  def dump(self, path):
    """Saves the pushdb as a properties file to the given path."""
    with open(path, 'w') as props:
      Properties.dump(self._props, props)


class ThriftGemerator(ScmPublish, Task):
  """Create ruby gems from thrift IDL files.

  ThriftGemerator can be configured in ``pants.ini`` as follows.

  ``gem-create`` section:

  * ``restrict_push_branches`` - Optional list of branches to restrict publishing to.
  * ``gems`` - Optional path of directory to create gems in.
  """

  _CONFIG_SECTION = 'gem-create'

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="thrift_gemerator_outdir",
                            help="Emit gems in to this directory.")

    option_group.add_option(mkflag("override"), dest="thrift_gemerator_override",
                            help="Version number override.")

    option_group.add_option(mkflag("dryrun"), mkflag("dryrun", negate=True),
                            dest="gem_publish_dryrun", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Runs through gemerator without actually pushing "
                                 "artifacts, editing publish dbs or otherwise writing data")

    option_group.add_option(mkflag("commit", negate=True),
                            dest="gem_publish_commit", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="Turns off commits of the push db for local testing.")

  def __init__(self, context, scm=None):
    Task.__init__(self, context)
    ScmPublish.__init__(self, scm or get_scm(),
                        self.context.config.getlist(
                          ThriftGemerator._CONFIG_SECTION, 'restrict_push_branches'))
    options = context.options
    self._output_dir = (options.thrift_gemerator_outdir or
                        self.get_workdir(section=ThriftGemerator._CONFIG_SECTION, workdir='gems'))
    self._override = options.thrift_gemerator_override
    self._dryrun = options.gem_publish_dryrun
    self._commit = options.gem_publish_commit

  def execute(self, targets):
    self.check_clean_master(commit=(not self._dryrun and self._commit))

    safe_mkdir(self._output_dir)

    self.gem(filter(is_ruby_library, self.context.target_roots))

  def gem(self, targets):
    for target in targets:
      thrift_files_with_root = []
      for source in target.derived_from.sources:
        thrift_files_with_root.append(os.path.join(target.derived_from.target_base , source))
      thrift_files = " ".join(thrift_files_with_root)
      gem_name = target.provides.name
      push_db = PushDb.load(target.provides.repo.push_db)
      gem_version = self._override or push_db.next_version(target)

      bases = set()
      for target in targets:
        bases.add(target.target_base)


      args = dict(
        include='-I "%s"' % '" -I "'.join(bases),
        name=gem_name,
        outdir=self._output_dir,
        version=gem_version,
        thrift_files=thrift_files,
        user=getpass.getuser(),
        publish=' --publish %s' % target.provides.repo.url if not self._dryrun else ''
      )

      cmd = 'thrift_gemerator --no-interactive --compiler-args="%(include)s" --gem=%(name)s --output=%(outdir)s ' \
            '--gem-version %(version)s%(publish)s %(thrift_files)s' % args
      log = self.context.log
      log.debug("Executing: %s" % cmd)
      result = subprocess.call(cmd, shell=True)
      if result != 0:
        raise TaskError('ThriftGemerator exited non-zero %i' % result)

      if self._dryrun:
        log.debug("Skipping gem publish for %s, but gem can be found at %s" % (gem_name, self._output_dir))
      else:
        push_db.set_version(target, gem_version)
        push_db.dump(target.provides.repo.push_db)

      if self._dryrun or not self._commit:
        log.debug("Skipping commit for %s" % gem_name)
      else:
        self.commit_push("gem %s" % gem_name)
        self.scm.refresh()
        self.scm.tag('gem-%(name)s-%(version)s' % args,
                     message='Publish of gem %(name)s-%(version)s initiated by %(user)s' % args)
