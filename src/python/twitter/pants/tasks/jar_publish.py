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

import getpass
import os
import pkgutil
import shutil
import subprocess

from twitter.common.collections import OrderedSet
from twitter.common.config import Properties
from twitter.common.dirutil import safe_open, safe_rmtree

from twitter.pants import get_buildroot, is_exported as provides, is_internal, is_java, pants
from twitter.pants.base import Address, BuildFile, ParseContext, Target
from twitter.pants.base.generator import Generator, TemplateData
from twitter.pants.targets import InternalTarget, AnnotationProcessor, JavaLibrary, ScalaLibrary
from twitter.pants.tasks import binary_utils, Task, TaskError

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
    return Semver(self.major, self.minor, self.patch + 1)

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
    """
      Given an internal target, return a JarDependency with the last published revision filled in.
    """
    jar_dep, db_get, _ = self._accessors_for_target(target)

    major = db_get('revision.major', '0')
    minor = db_get('revision.minor', '0')
    patch = db_get('revision.patch', '0')
    sha = db_get('revision.sha', None)
    semver = Semver(major, minor, patch)
    jar_dep.rev = semver.version()
    return jar_dep, semver, sha

  def set_version(self, target, version, sha):
    version = version if isinstance(version, Semver) else Semver.parse(version)
    _, _, db_set = self._accessors_for_target(target)
    db_set('revision.major', version.major)
    db_set('revision.minor', version.minor)
    db_set('revision.patch', version.patch)
    db_set('revision.sha', sha)

  def _accessors_for_target(self, target):
    jar_dep, id, exported = target._get_artifact_info()
    if not exported:
      raise ValueError

    def key(prefix):
      return '%s.%s%%%s' % (prefix, jar_dep.org, jar_dep.name)

    def getter(prefix, default=None):
      return self._props.get(key(prefix), default)

    def setter(prefix, value):
      self._props[key(prefix)] = value

    return jar_dep, getter, setter

  def dump(self, file):
    """Saves the pushdb as a properties file to the given path."""
    with open(file, 'w') as props:
      Properties.dump(self._props, props)


class PomWriter(object):
  @staticmethod
  def jardep(jar):
    def create_exclude(exclude):
      return TemplateData(
        org=exclude.org,
        name=exclude.name,
      )
    template_data = TemplateData(
      org=jar.org,
      name=jar.name,
      rev=jar.rev,
      scope='compile',
      excludes=None
    )
    if jar.excludes:
      template_data = template_data.extend(
        excludes=[create_exclude(exclude) for exclude in jar.excludes if exclude.name]
      )
    return template_data

  def __init__(self, get_db):
    self.get_db = get_db

  def write(self, target, path):
    dependencies = [self.internaldep(dep) for dep in target.internal_dependencies]
    dependencies.extend(PomWriter.jardep(dep) for dep in target.jar_dependencies if dep.rev)
    target_jar = self.internaldep(target).extend(dependencies=dependencies)

    with safe_open(path, 'w') as output:
      generator = Generator(pkgutil.get_data(__name__, os.path.join('jar_publish', 'pom.mk')),
                            artifact=target_jar)
      generator.write(output)

  def internaldep(self, target):
    jar, _, _ = self.get_db(target).as_jar_with_version(target)
    return PomWriter.jardep(jar)


class IvyWriter(object):
  def __init__(self, get_db):
    self.get_db = get_db

  @staticmethod
  def jardep(jar):
    return TemplateData(
      org = jar.org,
      module = jar.name,
      version = jar.rev,
      force = jar.force,
      excludes = [IvyWriter.create_exclude(exclude) for exclude in jar.excludes],
      transitive = jar.transitive,
      ext = jar.ext,
      url = jar.url,
      configurations = ';'.join(jar._configurations),
    )

  @staticmethod
  def create_exclude(exclude):
    return TemplateData(org = exclude.org, name = exclude.name)

  def write(self, target, path, confs=None):
    dependencies = [self.internaldep(dep) for dep in target.internal_dependencies]
    dependencies.extend(self.jardep(dep) for dep in target.jar_dependencies if dep.rev)

    excludes = []
    if target.excludes:
      excludes.extend(IvyWriter.create_exclude(exclude) for exclude in target.excludes)

    template_data = self.internaldep(target).extend(
      publications=set(confs) if confs else set(),
      dependencies=dependencies,
      excludes=excludes
    )

    with safe_open(path, 'w') as output:
      generator = Generator(pkgutil.get_data(__name__, os.path.join('ivy_resolve', 'ivy.mk')),
                            lib=template_data)
      generator.write(output)

  def internaldep(self, target):
    jar, _, _ = self.get_db(target).as_jar_with_version(target)
    return TemplateData(
      org = jar.org,
      module = jar.name,
      version = jar.rev,
      force = False,
      excludes = [IvyWriter.create_exclude(exclude) for exclude in target.excludes],
      transitive = True,
      ext = None,
      url = None,
      configurations = 'default',
    )


def is_exported(target):
  return provides(target) and (
    isinstance(target, AnnotationProcessor)
    or isinstance(target, JavaLibrary)
    or isinstance(target, ScalaLibrary)
  )

class JarPublish(Task):

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    # TODO(John Sirois): Support a preview mode that outputs a file with entries like:
    # artifact id:
    # revision:
    # publish: (true|false)
    # changelog:
    #
    # Allow re-running this goal with the file as input to support forcing an arbitrary set of
    # revisions and supply of hand endited changelogs.

    option_group.add_option(mkflag("dryrun"), mkflag("dryrun", negate=True),
                            dest="jar_publish_dryrun", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Runs through a push without actually pushing "
                                 "artifacts, editing publish dbs or otherwise writing data")

    option_group.add_option(mkflag("commit", negate=True),
                            dest="jar_publish_commit", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="Turns off commits of the push db for local testing.")

    option_group.add_option(mkflag("repo-prefix"), dest="jar_publish_repo_prefix",
                            help="Prefix provided jars repo names with this string - useful for "
                                 "swapping out a set of standard repos for another.")

    option_group.add_option(mkflag("transitive"), mkflag("transitive", negate=True),
                            dest="jar_publish_transitive", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Publishes the specified targets and all their "
                                 "internal dependencies transitively.")

    option_group.add_option(mkflag("force"), mkflag("force", negate=True),
                            dest="jar_publish_force", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Forces pushing jars even if there have been no "
                                 "changes since the last push.")

    flag = mkflag('override')
    option_group.add_option(flag, action='append', dest='jar_publish_overrides',
                            help='''Specifies a published jar revision override in the form:
                            ([org]#[name]|[target spec])=[new revision]

                            For example, to specify 2 overrides:
                            %(flag)s=com.twitter.common#quantity=0.1.2 \\
                            %(flag)s=src/java/com/twitter/common/base=1.0.0 \\
                            ''' % dict(flag=flag))

    flag = mkflag("restart-at")
    option_group.add_option(flag, dest="jar_publish_restart_at",
                            help='''Restart a fail push at the given jar.  Jars can be identified by
                            maven coordinate [org]#[name] or target.

                            For example:
                            %(flag)s=com.twitter.common#quantity

                            Or:
                            %(flag)s=src/java/com/twitter/common/base
                            ''' % dict(flag=flag))

  def __init__(self, context):
    Task.__init__(self, context)

    self.outdir = context.config.get('jar-publish', 'workdir')
    self.cachedir = os.path.join(self.outdir, 'cache')
    self.repos = context.config.getdict('jar-publish', 'repos')
    self.repo_prefix = context.options.jar_publish_repo_prefix or ''

    self.ivycp = context.config.getlist('ivy', 'classpath')
    self.ivysettings = context.config.get('ivy', 'ivy_settings')

    self.dryrun = context.options.jar_publish_dryrun
    self.commit = context.options.jar_publish_commit
    self.transitive = context.options.jar_publish_transitive
    self.force = context.options.jar_publish_force

    def parse_jarcoordinate(coordinate):
      components = coordinate.split('#', 1)
      if len(components) == 2:
        org, name = components
        return org, name
      else:
        try:
          address = Address.parse(get_buildroot(), coordinate)
          try:
            target = Target.get(address)
            if not target:
              siblings = Target.get_all_addresses(address.buildfile)
              prompt = 'did you mean' if len(siblings) == 1 else 'maybe you meant one of these'
              raise TaskError('%s => %s?:\n    %s' % (address, prompt,
                                                      '\n    '.join(str(a) for a in siblings)))
            if not is_exported(target):
              raise TaskError('%s is not an exported target' % coordinate)
            return target.provides.org, target.provides.name
          except (ImportError, SyntaxError, TypeError):
            raise TaskError('Failed to parse %s' % address.buildfile.relpath)
        except IOError:
          raise TaskError('No BUILD file could be found at %s' % coordinate)

    self.overrides = {}
    if context.options.jar_publish_overrides:
      def parse_override(override):
        try:
          coordinate, rev = override.split('=', 1)
          try:
            rev = Semver.parse(rev)
          except ValueError:
            raise TaskError('Invalid version: %s' % rev)
          return parse_jarcoordinate(coordinate), rev
        except ValueError:
          raise TaskError('Invalid override: %s' % override)

      self.overrides.update(parse_override(o) for o in context.options.jar_publish_overrides)

    self.restart_at = None
    if context.options.jar_publish_restart_at:
      self.restart_at = parse_jarcoordinate(context.options.jar_publish_restart_at)

    context.products.require('jars')
    context.products.require('source_jars')
    context.products.require('javadoc_jars')

  def execute(self, targets):
    self.check_clean_master()

    pushdbs = {}
    def get_db(target):
      dbfile = target.provides.repo.push_db
      result = pushdbs.get(dbfile)
      if not result:
        db = PushDb.load(dbfile)
        repo = self.repos[(self.repo_prefix + target.provides.repo.name)]
        result = (db, dbfile, repo)
        pushdbs[dbfile] = result
      return result

    def stage_artifacts(target, jar, version, confs=None):
      def artifact_path(name=None, suffix='', extension='jar'):
        return os.path.join(self.outdir, jar.org, jar.name,
                            '%s-%s%s.%s' % ((name or jar.name), version, suffix, extension))

      with safe_open(artifact_path(suffix='-CHANGELOG', extension='txt'), 'w') as changelog_file:
        changelog_file.write(changes)

      def get_pushdb(target):
        return get_db(target)[0]

      PomWriter(get_pushdb).write(target, artifact_path(extension='pom'))

      ivyxml = artifact_path(name='ivy', extension='xml')
      IvyWriter(get_pushdb).write(target, ivyxml, confs)

      def copy(typename, suffix=''):
        genmap = self.context.products.get(typename)
        for basedir, jars in genmap.get(target).items():
          for artifact in jars:
            shutil.copy(os.path.join(basedir, artifact), artifact_path(suffix=suffix))

      copy('jars')
      if is_java(target):
        copy('javadoc_jars', '-javadoc')
      copy('source_jars', '-sources')

      return ivyxml

    if self.overrides:
      print 'Publishing with revision overrides:\n  %s' % '\n  '.join('%s#%s=%s' % (org, name, rev)
          for (org, name), rev in self.overrides.items())

    head_sha = self.check_output(['git', 'rev-parse', 'HEAD']).strip()

    safe_rmtree(self.outdir)
    published = []
    skip = (self.restart_at is not None)
    for target in self.exported_targets():
      pushdb, dbfile, repo = get_db(target)
      jar, semver, sha = pushdb.as_jar_with_version(target)

      published.append(jar)

      if skip and (jar.org, jar.name) == self.restart_at:
        skip = False

      newver = self.overrides.get((jar.org, jar.name)) or semver.bump()

      changes = self.changelog(target, sha)
      if not changes and not self.force:
        print 'No changes for %s#%s;%s' % (jar.org, jar.name, semver.version())
        stage_artifacts(target, jar, (newver if self.force else semver).version())
      elif skip:
        print 'Skipping %s#%s;%s to resume at %s#%s' % (
          jar.org,
          jar.name,
          (newver if self.force else semver).version(),
          self.restart_at[0],
          self.restart_at[1]
        )
        stage_artifacts(target, jar, semver.version())
      else:
        if not self.dryrun:
          # Confirm push looks good
          if not changes:
            print 'No changes for %s#%s;%s - forced push.' % (jar.org, jar.name, semver.version())
          else:
            print '\nChanges for %s#%s since %s @ %s:\n\n%s' % (
              jar.org, jar.name, semver.version(), sha, changes
            )
          push = raw_input('Publish %s#%s with revision %s ? [y|N] ' % (
            jar.org, jar.name, newver.version()
          ))
          print '\n'
          if push.strip().lower() != 'y':
            # TODO(John Sirois): Use context.stop()
            raise TaskError('User aborted push')

        pushdb.set_version(target, newver, head_sha)
        ivyxml = stage_artifacts(target, jar, newver.version(), confs=repo['confs'])
        if self.dryrun:
          print 'Skipping publish of %s#%s;%s in test mode.' % (jar.org, jar.name, newver.version())
        else:
          resolver = repo['resolver']

          # Get authentication for the publish repo if needed
          jvmargs = []
          auth = repo['auth']
          if auth:
            buildfile = BuildFile(get_buildroot(), '.', must_exist=False)
            def load_credentials():
              return list(pants(auth).resolve()).pop()
            credentials = ParseContext(buildfile).do_in_context(load_credentials)
            jvmargs.append(credentials.username())
            jvmargs.append(credentials.password())

          # Do the publish
          ivysettings = self.generate_ivysettings(published)
          args = [
            '-settings', ivysettings,
            '-ivy', ivyxml,
            '-deliverto', '%s/[organisation]/[module]/ivy-[revision].xml' % self.outdir,
            '-publish', resolver,
            '-publishpattern',
              '%s/[organisation]/[module]/[artifact]-[revision](-[classifier]).[ext]' % self.outdir,
            '-revision', newver.version(),
            '-m2compatible',
          ]
          result = binary_utils.runjava(jvmargs=jvmargs, classpath=self.ivycp, args=args)
          if result != 0:
            raise TaskError('Failed to push %s#%s;%s - ivy failed with %d' % (
              jar.org, jar.name, newver.version(), result)
            )

          pushdb.dump(dbfile)
          self.commit_push(jar.org, jar.name, newver.version(), head_sha)

  def exported_targets(self):
    candidates = set(self.context.targets() if self.transitive else self.context.target_roots)
    def exportable(target):
      return target in candidates and is_exported(target) and is_internal(target)
    return OrderedSet(filter(exportable,
                             reversed(InternalTarget.sort_targets(filter(exportable, candidates)))))

  def changelog(self, target, sha):
    cmd = ['git', 'whatchanged', '--stat', '-M', '-C']
    if sha:
      cmd.append('%s..HEAD' % sha)
    cmd.append('--')
    cmd.extend(os.path.join(target.target_base, source) for source in target.sources)
    cmd.append(target.address.buildfile.relpath)
    return self.check_output(cmd)

  def check_clean_master(self):
    if self.dryrun or not self.commit:
      print 'Skipping check for a clean master in test mode.'
    else:
      branch = self.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD']).strip()
      if branch != 'master':
        raise TaskError('Can only push from master, currently on branch: %s' % branch)

      self.check_call(['git', 'diff', '--exit-code', '--quiet'],
                      failuremsg='Can only push from a clean master, workspace is dirty')

      self.check_call(['git', 'diff', '--exit-code', '--cached', '--quiet'],
                      failuremsg='Can only push from a clean master, index is dirty')

  def commit_push(self, org, name, rev, sha):
    if self.commit:
      args = dict(
        org=org,
        name=name,
        rev=rev,
        user=getpass.getuser(),
        cause='with forced revision' if (org, name) in self.overrides else '(autoinc)'
      )
      self.check_call(['git', 'pull', '--ff-only', '--tags', 'origin', 'master'])
      self.check_call(['git', 'tag' , '-a',
                       '-m', 'Publish of %(org)s#%(name)s initiated by %(user)s %(cause)s' % args,
                       '%(org)s-%(name)s-%(rev)s' % args, sha])

      self.check_call(['git', 'commit' , '-a',
                       '-m', 'pants build committing publish data for push of '
                             '%(org)s#%(name)s;%(rev)s' % args])

      self.check_call(['git', 'push' , 'origin', 'master', '--tags'])

  def check_call(self, cmd, failuremsg=None):
    self.log_call(cmd)
    result = subprocess.call(cmd)
    self.check_result(cmd, result, failuremsg)

  def check_output(self, cmd, failuremsg=None):
    self.log_call(cmd)
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = process.communicate()
    self.check_result(cmd, process.returncode, failuremsg)
    return out

  def log_call(self, cmd):
    self.context.log.debug('Executing: %s' % ' '.join(cmd))

  def check_result(self, cmd, result, failuremsg=None):
    if result != 0:
      raise TaskError(failuremsg or '%s failed with exit code %d' % (' '.join(cmd), result))

  def generate_ivysettings(self, publishedjars):
    template = pkgutil.get_data(__name__, os.path.join('jar_publish', 'ivysettings.mk'))
    with safe_open(os.path.join(self.outdir, 'ivysettings.xml'), 'w') as wrapper:
      generator = Generator(template,
                            ivysettings=self.ivysettings,
                            dir=self.outdir,
                            cachedir=self.cachedir,
                            published=[TemplateData(org=jar.org, name=jar.name)
                                       for jar in publishedjars])
      generator.write(wrapper)
      return wrapper.name

