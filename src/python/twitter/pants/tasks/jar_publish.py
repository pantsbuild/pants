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

from __future__ import print_function

import copy
import hashlib
import getpass
import os
import pkgutil
import shutil
import subprocess

from collections import defaultdict

from twitter.common.collections import OrderedDict, OrderedSet
from twitter.common.config import Properties
from twitter.common.dirutil import safe_open, safe_rmtree

from twitter.pants import (
  binary_util,
  get_buildroot,
  get_scm,
  is_exported as provides,
  is_internal,
  is_java,
  is_codegen)
from twitter.pants.base import Address, Target
from twitter.pants.base.generator import Generator, TemplateData
from twitter.pants.targets import (
  InternalTarget,
  AnnotationProcessor,
  JavaLibrary,
  ScalaLibrary,
  JavaThriftLibrary)
from twitter.pants.tasks import Task, TaskError

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

    major = int(db_get('revision.major', '0'))
    minor = int(db_get('revision.minor', '0'))
    patch = int(db_get('revision.patch', '0'))
    snapshot = db_get('revision.snapshot', 'false').lower() == 'true'
    sha = db_get('revision.sha', None)
    fingerprint = db_get('revision.fingerprint', None)
    semver = Semver(major, minor, patch, snapshot=snapshot)
    jar_dep.rev = semver.version()
    return jar_dep, semver, sha, fingerprint

  def set_version(self, target, version, sha, fingerprint):
    version = version if isinstance(version, Semver) else Semver.parse(version)
    _, _, db_set = self._accessors_for_target(target)
    db_set('revision.major', version.major)
    db_set('revision.minor', version.minor)
    db_set('revision.patch', version.patch)
    db_set('revision.snapshot', str(version.snapshot).lower())
    db_set('revision.sha', sha)
    db_set('revision.fingerprint', fingerprint)

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


class DependencyWriter(object):
  """
    Builds up a template data representing a target and applies this to a template to produce a
    dependency descriptor.
  """

  def __init__(self, get_db, template_relpath):
    self.get_db = get_db
    self.template_relpath = template_relpath

  def write(self, target, path, confs=None, synth=False):
    def as_jar(internal_target, is_tgt=False):
      jar, _, _, _ = self.get_db(internal_target).as_jar_with_version(internal_target)
      if synth and is_tgt:
        jar.name = jar.name + '-only'
      return jar

    # TODO(John Sirois): a dict is used here to de-dup codegen targets which have both the original
    # codegen target - say java_thrift_library - and the synthetic generated target (java_library)
    # Consider reworking codegen tasks to add removal of the original codegen targets when rewriting
    # the graph
    dependencies = OrderedDict()
    internal_codegen = {}
    for dep in target.internal_dependencies:
      jar = as_jar(dep)
      dependencies[(jar.org, jar.name)] = self.internaldep(jar, dep, synth)
      if is_codegen(dep):
        internal_codegen[jar.name] = jar.name
    for jar in target.jar_dependencies:
      if jar.rev:
        dependencies[(jar.org, jar.name)] = self.jardep(jar)
    target_jar = self.internaldep(as_jar(target, is_tgt=True)).extend(
      dependencies=dependencies.values()
    )

    template_kwargs = self.templateargs(target_jar, confs, synth)
    with safe_open(path, 'w') as output:
      template = pkgutil.get_data(__name__, self.template_relpath)
      Generator(template, **template_kwargs).write(output)

  def templateargs(self, target_jar, confs=None, synth=False):
    """
      Subclasses must return a dict for use by their template given the target jar template data
      and optional specific ivy configurations.
    """
    raise NotImplementedError()

  def internaldep(self, jar_dependency, dep=None, synth=False):
    """
      Subclasses must return a template data for the given internal target (provided in jar
      dependency form).
    """
    raise NotImplementedError()

  def jardep(self, jar_dependency):
    """Subclasses must return a template data for the given external jar dependency."""
    raise NotImplementedError()

  def create_exclude(self, exclude):
    return TemplateData(org=exclude.org, name=exclude.name)


class PomWriter(DependencyWriter):
  def __init__(self, get_db):
    super(PomWriter, self).__init__(get_db, os.path.join('templates', 'jar_publish', 'pom.mustache'))

  def templateargs(self, target_jar, confs=None, synth=False):
    return dict(artifact=target_jar)

  def jardep(self, jar, classifier=None):
    return TemplateData(
      org=jar.org,
      name=jar.name + ('-only' if classifier == 'idl' else ''),
      rev=jar.rev,
      scope='runtime' if classifier == 'idl' else 'compile',
      classifier=classifier,
      excludes=[self.create_exclude(exclude) for exclude in jar.excludes if exclude.name]
    )

  def internaldep(self, jar_dependency, dep=None, synth=False):
    classifier = 'idl' if dep and is_codegen(dep) and synth else None
    return self.jardep(jar_dependency, classifier=classifier)


class IvyWriter(DependencyWriter):
  def __init__(self, get_db):
    super(IvyWriter, self).__init__(get_db, os.path.join('templates', 'ivy_resolve', 'ivy.mustache'))

  def templateargs(self, target_jar, confs=None, synth=False):
    return dict(lib=target_jar.extend(
      is_idl=synth,
      publications=dict((conf, True) for conf in confs or ()),
    ))

  def _jardep(self, jar, transitive=True, configurations='default', classifier=None):
    return TemplateData(
      org=jar.org,
      module=jar.name + ('-only' if classifier == 'idl' else ''),
      version=jar.rev,
      mutable=False,
      force=jar.force,
      excludes=[self.create_exclude(exclude) for exclude in jar.excludes],
      transitive=transitive,
      artifacts=jar.artifacts,
      is_idl=(classifier == 'idl'),
      configurations=configurations,
    )

  def jardep(self, jar):
    return self._jardep(jar,
      transitive=jar.transitive,
      configurations=';'.join(jar._configurations)
    )

  def internaldep(self, jar_dependency, dep=None, synth=False):
    classifier = 'idl' if dep and is_codegen(dep) and synth else None
    return self._jardep(jar_dependency, classifier=classifier)


def is_exported(target):
  return provides(target) and (
    isinstance(target, AnnotationProcessor)
    or isinstance(target, JavaLibrary)
    or isinstance(target, ScalaLibrary)
  )


def coordinate(org, name, rev=None):
  return '%s#%s;%s' % (org, name, rev) if rev else '%s#%s' % (org, name)


def jar_coordinate(jar, rev=None):
  return coordinate(jar.org, jar.name, rev or jar.rev)


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

    local_flag = mkflag("local")
    option_group.add_option(local_flag, dest="jar_publish_local",
                            help="Publishes jars to a maven repository on the local filesystem at "
                                 "the specified path.")

    option_group.add_option(mkflag("local-snapshot"), mkflag("local-snapshot", negate=True),
                            dest="jar_publish_local_snapshot", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%%default] If %s is specified, publishes jars with '-SNAPSHOT' "
                                 "revisions." % local_flag)

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

  def __init__(self, context, scm=None, restrict_push_branches=None):
    Task.__init__(self, context)

    self.scm = scm or get_scm()
    self.restrict_push_branches = frozenset(restrict_push_branches or ())
    self.outdir = context.config.get('jar-publish', 'workdir')
    self.cachedir = os.path.join(self.outdir, 'cache')

    if context.options.jar_publish_local:
      local_repo = dict(
        resolver='publish_local',
        path=os.path.abspath(os.path.expanduser(context.options.jar_publish_local)),
        confs=context.config.getlist('jar-publish', 'publish_local_confs', default=['*']),
        auth=None
      )
      self.repos = defaultdict(lambda: local_repo)
      self.commit = False
      self.snapshot = context.options.jar_publish_local_snapshot
    else:
      self.repos = context.config.getdict('jar-publish', 'repos')
      for repo, data in self.repos.items():
        auth = data.get('auth')
        if auth:
          credentials = context.resolve(auth).next()
          user = credentials.username()
          password = credentials.password()
          self.context.log.debug('Found auth for repo: %s %s:%s' % (repo, user, password))
          data['auth'] = (user, password)
      self.commit = context.options.jar_publish_commit
      self.snapshot = False

    self.ivycp = context.config.getlist('ivy', 'classpath')
    self.ivysettings = context.config.get('ivy', 'ivy_settings')

    self.dryrun = context.options.jar_publish_dryrun
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
          except ValueError as e:
            raise TaskError('Invalid version %s: %s' % (rev, e))
          return parse_jarcoordinate(coordinate), rev
        except ValueError:
          raise TaskError('Invalid override: %s' % override)

      self.overrides.update(parse_override(o) for o in context.options.jar_publish_overrides)

    self.restart_at = None
    if context.options.jar_publish_restart_at:
      self.restart_at = parse_jarcoordinate(context.options.jar_publish_restart_at)

    context.products.require('jars')
    context.products.require('source_jars')
    context.products.require('idl_jars')
    context.products.require('javadoc_jars')

  def execute(self, targets):
    self.check_clean_master()

    exported_targets = self.exported_targets()
    self.check_targets(exported_targets)

    pushdbs = {}
    def get_db(target):
      if target.provides is None:
        raise TaskError('trying to publish target %r which does not provide an artifact' % target)
      dbfile = target.provides.repo.push_db
      result = pushdbs.get(dbfile)
      if not result:
        db = PushDb.load(dbfile)
        repo = self.repos[target.provides.repo.name]
        result = (db, dbfile, repo)
        pushdbs[dbfile] = result
      return result

    def fingerprint_internal(target):
      if not is_internal(target):
        raise ValueError('Expected an internal target for fingerprinting, got %s' % target)
      pushdb, _, _ = get_db(target)
      _, _, _, fingerprint = pushdb.as_jar_with_version(target)
      return fingerprint or '0.0.0'

    def lookup_synthetic_target(target):
      # lookup the source target that generated this synthetic target
      revmap = self.context.products.get('java:rev')
      if revmap.get(target):
        for _, codegen_targets in revmap.get(target).items():
          for codegen_target in codegen_targets:
            # TODO(phom) this only works for Thrift Library, not Protobuf
            if isinstance(codegen_target, JavaThriftLibrary):
              return codegen_target

    def stage_artifacts(target, jar, version, changelog, confs=None, synth_target=None):
      def artifact_path(name=None, suffix='', extension='jar', artifact_ext=''):
        return os.path.join(self.outdir, jar.org, jar.name + artifact_ext,
                            '%s%s-%s%s.%s' % (
                              (name or jar.name),
                              artifact_ext if name != 'ivy' else '',
                              version,
                              suffix,
                              extension
                            ))

      def get_pushdb(target):
        return get_db(target)[0]

      with safe_open(artifact_path(suffix='-CHANGELOG', extension='txt'), 'w') as changelog_file:
        changelog_file.write(changelog)
      ivyxml = artifact_path(name='ivy', extension='xml')
      IvyWriter(get_pushdb).write(target, ivyxml, confs)
      PomWriter(get_pushdb).write(target, artifact_path(extension='pom'))

      idl_ivyxml = None
      if synth_target:
        changelog_path = artifact_path(suffix='-CHANGELOG', extension='txt', artifact_ext='-only')
        with safe_open(changelog_path, 'w') as changelog_file:
          changelog_file.write(changelog)
        idl_ivyxml = artifact_path(name='ivy', extension='xml', artifact_ext='-only')
        # use idl publication spec in ivy for idl artifact
        IvyWriter(get_pushdb).write(synth_target, idl_ivyxml, ['idl'], synth=True)
        PomWriter(get_pushdb).write(synth_target,
                                    artifact_path(extension='pom', artifact_ext='-only'),
                                    synth=True)

      def copy(tgt, typename, suffix='', artifact_ext=''):
        genmap = self.context.products.get(typename)
        mapping = genmap.get(tgt)
        if not mapping:
          print('no mapping for %s' % tgt)
        else:
          for basedir, jars in mapping.items():
            for artifact in jars:
              path = artifact_path(suffix=suffix, artifact_ext=artifact_ext)
              shutil.copy(os.path.join(basedir, artifact), path)

      copy(target, typename='jars')
      copy(target, typename='source_jars', suffix='-sources')
      if (synth_target):
        copy(synth_target, typename='idl_jars', suffix='-idl', artifact_ext='-only')

      if is_java(target):
        copy(target, typename='javadoc_jars', suffix='-javadoc')


      return ivyxml, idl_ivyxml

    if self.overrides:
      print('Publishing with revision overrides:\n  %s' % '\n  '.join(
        '%s=%s' % (coordinate(org, name), rev) for (org, name), rev in self.overrides.items()
      ))

    head_sha = self.scm.commit_id

    safe_rmtree(self.outdir)
    published = []
    skip = (self.restart_at is not None)
    for target in exported_targets:
      synth_target = lookup_synthetic_target(target)
      pushdb, dbfile, repo = get_db(target)
      jar, semver, sha, fingerprint = pushdb.as_jar_with_version(target)

      if synth_target:
        # add idl artifact to the published cache
        tmp_jar = copy.copy(jar)
        tmp_jar.name = tmp_jar.name + '-only'
        published.append(tmp_jar)
      published.append(jar)

      if skip and (jar.org, jar.name) == self.restart_at:
        skip = False

      newver = self.overrides.get((jar.org, jar.name)) or semver.bump()
      if self.snapshot:
        newver = newver.make_snapshot()

      if newver <= semver:
        raise TaskError('Requested version %s must be greater than the current version %s' % (
          newver.version(), semver.version()
        ))

      newfingerprint = self.fingerprint(target, fingerprint_internal)
      no_changes = newfingerprint == fingerprint

      if no_changes:
        changelog = 'No changes for %s - forced push.\n' % jar_coordinate(jar, semver.version())
      else:
        changelog = self.changelog(target, sha) or 'Direct dependencies changed.\n'

      if no_changes and not self.force:
        print('No changes for %s' % jar_coordinate(jar, semver.version()))
        stage_artifacts(target, jar, (newver if self.force else semver).version(), changelog,
                        synth_target=synth_target)
      elif skip:
        print('Skipping %s to resume at %s' % (
          jar_coordinate(jar, (newver if self.force else semver).version()),
          coordinate(self.restart_at[0], self.restart_at[1])
        ))
        stage_artifacts(target, jar, semver.version(), changelog, synth_target=synth_target)
      else:
        if not self.dryrun:
          # Confirm push looks good
          if no_changes:
            print(changelog)
          else:
            print('\nChanges for %s since %s @ %s:\n\n%s' % (
              coordinate(jar.org, jar.name), semver.version(), sha, changelog
            ))
          push = raw_input('Publish %s with revision %s ? [y|N] ' % (
            coordinate(jar.org, jar.name), newver.version()
          ))
          print('\n')
          if push.strip().lower() != 'y':
            raise TaskError('User aborted push')

        pushdb.set_version(target, newver, head_sha, newfingerprint)

        ivyxml, idl_ivyxml = stage_artifacts(target, jar, newver.version(), changelog,
                                             confs=repo['confs'], synth_target=synth_target)

        if self.dryrun:
          print('Skipping publish of %s in test mode.' % jar_coordinate(jar, newver.version()))
        else:
          resolver = repo['resolver']
          path = repo.get('path')

          # Get authentication for the publish repo if needed
          jvmargs = []
          auth = repo['auth']
          if auth:
            user, password = auth
            jvmargs.append('-Dlogin=%s' % user)
            jvmargs.append('-Dpassword=%s' % password)

          # Do the publish
          ivysettings = self.generate_ivysettings(published, publish_local=path)
          opts = [
            '-settings', ivysettings,
            '-ivy', ivyxml,
            '-deliverto', '%s/[organisation]/[module]/ivy-[revision].xml' % self.outdir,
            '-publish', resolver,
            '-publishpattern',
              '%s/[organisation]/[module]/[artifact]-[revision](-[classifier]).[ext]' % self.outdir,
            '-revision', newver.version(),
            '-m2compatible',
          ]
          if self.snapshot:
            opts.append('-overwrite')

          result = binary_util.runjava_indivisible(jvmargs=jvmargs, classpath=self.ivycp, opts=opts)
          if result != 0:
            raise TaskError('Failed to push %s - ivy failed with %d' % (
              jar_coordinate(jar, newver.version()), result)
            )

          if (synth_target):
            opts = [
              '-settings', ivysettings,
              '-ivy', idl_ivyxml,
              '-deliverto', '%s/[organisation]/[module]/ivy-[revision].xml' % self.outdir,
              '-publish', resolver,
              '-publishpattern', '%s/[organisation]/[module]/'
                                 '[artifact]-[revision](-[classifier]).[ext]' % self.outdir,
              '-revision', newver.version(),
              '-m2compatible',
            ]
            if self.snapshot:
              opts.append('-overwrite')

            result = binary_util.runjava_indivisible(jvmargs=jvmargs, classpath=self.ivycp,
                                                     opts=opts)
            if result != 0:
              raise TaskError('Failed to push %s - ivy failed with %d' % (
                jar_coordinate(jar, newver.version()), result)
              )

          if self.commit:
            pushdb.dump(dbfile)
            self.commit_push(jar.org, jar.name, newver.version(), head_sha)

  def check_targets(self, targets):
    invalid = filter(lambda (t, reason): reason, zip(targets, map(self.is_invalid, targets)))
    if invalid:
      target_reasons = '\n\t'.join('%s: %s' % (tgt.address, reason) for tgt, reason in invalid)
      params = dict(
        roots=' '.join(str(t.address) for t in self.context.target_roots),
        reasons=target_reasons
      )
      raise TaskError('The following targets must be fixed or removed in order to '
                      'publish %(roots)s:\n\t%(reasons)s' % params)

  def is_invalid(self, target):
    if not target.sources:
      return 'No sources'

  def exported_targets(self):
    candidates = set(self.context.targets() if self.transitive else self.context.target_roots)
    def exportable(target):
      return target in candidates and is_exported(target) and is_internal(target)
    return OrderedSet(filter(exportable,
                             reversed(InternalTarget.sort_targets(filter(exportable, candidates)))))

  def fingerprint(self, target, fingerprint_internal):
    sha = hashlib.sha1()

    for source in sorted(target.sources):
      path = os.path.join(target.target_base, source)
      with open(path) as fd:
        sha.update(source)
        sha.update(fd.read())

    # TODO(John Sirois): handle resources and circular dep scala_library java_sources

    for jarsig in sorted([jar_coordinate(j) for j in target.jar_dependencies if j.rev]):
      sha.update(jarsig)

    internal_dependencies = sorted(target.internal_dependencies, key=lambda t: t.id)
    for internal_target in internal_dependencies:
      fingerprint = fingerprint_internal(internal_target)
      sha.update(fingerprint)

    return sha.hexdigest()

  def changelog(self, target, sha):
    return self.scm.changelog(from_commit=sha,
                              files=[os.path.join(target.target_base, source)
                                     for source in target.sources])

  def check_clean_master(self):
    if self.dryrun or not self.commit:
      print('Skipping check for a clean master in test mode.')
    else:
      if self.restrict_push_branches:
        branch = self.scm.branch_name
        if branch not in self.restrict_push_branches:
          raise TaskError('Can only push from %s, currently on branch: %s' % (
            ' '.join(sorted(self.restrict_push_branches)), branch
          ))

      changed_files = self.scm.changed_files()
      if changed_files:
        raise TaskError('Can only push from a clean branch, found : %s' % ' '.join(changed_files))

  def commit_push(self, org, name, rev, sha):
    args = dict(
      org=org,
      name=name,
      rev=rev,
      coordinate=coordinate(org, name, rev),
      user=getpass.getuser(),
      cause='with forced revision' if (org, name) in self.overrides else '(autoinc)'
    )

    self.scm.refresh()
    self.scm.commit('pants build committing publish data for push of %(coordinate)s' % args)

    self.scm.refresh()
    self.scm.tag('%(org)s-%(name)s-%(rev)s' % args,
                 message='Publish of %(coordinate)s initiated by %(user)s %(cause)s' % args)

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

  def generate_ivysettings(self, publishedjars, publish_local=None):
    template_relpath = os.path.join('templates', 'jar_publish', 'ivysettings.mustache')
    template = pkgutil.get_data(__name__, template_relpath)
    with safe_open(os.path.join(self.outdir, 'ivysettings.xml'), 'w') as wrapper:
      generator = Generator(template,
                            ivysettings=self.ivysettings,
                            dir=self.outdir,
                            cachedir=self.cachedir,
                            published=[TemplateData(org=jar.org, name=jar.name)
                                       for jar in publishedjars],
                            publish_local=publish_local)
      generator.write(wrapper)
      return wrapper.name
