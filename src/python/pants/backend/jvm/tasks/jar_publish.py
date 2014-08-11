# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import functools
import getpass
import hashlib
import logging
import os
import pkgutil
import shutil
import sys

from twitter.common.collections import OrderedDict, OrderedSet
from twitter.common.config import Properties
from twitter.common.log.options import LogOptions

from pants.backend.core.tasks.scm_publish import ScmPublish, Semver
from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.targets.jarable import Jarable
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.jar_task import JarTask
from pants.base.address import Address
from pants.base.build_environment import get_buildroot, get_scm
from pants.base.build_graph import sort_targets
from pants.base.exceptions import TaskError
from pants.base.generator import Generator, TemplateData
from pants.base.target import Target
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy import Ivy
from pants.util.dirutil import safe_mkdir, safe_open, safe_rmtree


class PushDb(object):
  @staticmethod
  def load(path):
    """Loads a pushdb maintained in a properties file at the given path."""
    with open(path, 'r') as props:
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
    jar_dep, _, exported = target.get_artifact_info()
    if not exported:
      raise ValueError

    def key(prefix):
      return '%s.%s%%%s' % (prefix, jar_dep.org, jar_dep.name)

    def getter(prefix, default=None):
      return self._props.get(key(prefix), default)

    def setter(prefix, value):
      self._props[key(prefix)] = value

    return jar_dep, getter, setter

  def dump(self, path):
    """Saves the pushdb as a properties file to the given path."""
    with open(path, 'w') as props:
      Properties.dump(self._props, props)


class DependencyWriter(object):
  """
    Builds up a template data representing a target and applies this to a template to produce a
    dependency descriptor.
  """

  @staticmethod
  def create_exclude(exclude):
    return TemplateData(org=exclude.org, name=exclude.name)

  def __init__(self, get_db, template_relpath, template_package_name=None):
    self.get_db = get_db
    self.template_package_name = template_package_name or __name__
    self.template_relpath = template_relpath

  def write(self, target, path, confs=None):
    def as_jar(internal_target):
      jar, _, _, _ = self.get_db(internal_target).as_jar_with_version(internal_target)
      return jar

    # TODO(John Sirois): a dict is used here to de-dup codegen targets which have both the original
    # codegen target - say java_thrift_library - and the synthetic generated target (java_library)
    # Consider reworking codegen tasks to add removal of the original codegen targets when rewriting
    # the graph
    dependencies = OrderedDict()
    internal_codegen = {}
    configurations = set(confs or [])
    for dep in target_internal_dependencies(target):
      jar = as_jar(dep)
      dependencies[(jar.org, jar.name)] = self.internaldep(jar, dep)
      if dep.is_codegen:
        internal_codegen[jar.name] = jar.name
    for jar in target.jar_dependencies:
      if jar.rev:
        dependencies[(jar.org, jar.name)] = self.jardep(jar)
        configurations |= set(jar._configurations)

    target_jar = self.internaldep(
                     as_jar(target),
                     configurations=list(configurations)).extend(dependencies=dependencies.values())

    template_kwargs = self.templateargs(target_jar, confs)
    with safe_open(path, 'w') as output:
      template = pkgutil.get_data(self.template_package_name, self.template_relpath)
      Generator(template, **template_kwargs).write(output)

  def templateargs(self, target_jar, confs=None):
    """
      Subclasses must return a dict for use by their template given the target jar template data
      and optional specific ivy configurations.
    """
    raise NotImplementedError()

  def internaldep(self, jar_dependency, dep=None, configurations=None):
    """
      Subclasses must return a template data for the given internal target (provided in jar
      dependency form).
    """
    raise NotImplementedError()

  def jardep(self, jar_dependency):
    """Subclasses must return a template data for the given external jar dependency."""
    raise NotImplementedError()


class PomWriter(DependencyWriter):
  def __init__(self, get_db):
    super(PomWriter, self).__init__(
        get_db,
        os.path.join('templates', 'jar_publish', 'pom.mustache'))

  def templateargs(self, target_jar, confs=None):
    return dict(artifact=target_jar)

  def jardep(self, jar):
    return TemplateData(
        org=jar.org,
        name=jar.name,
        rev=jar.rev,
        scope='compile',
        excludes=[self.create_exclude(exclude) for exclude in jar.excludes if exclude.name])

  def internaldep(self, jar_dependency, dep=None, configurations=None):
    return self.jardep(jar_dependency)


class IvyWriter(DependencyWriter):
  JAVADOC_CONFIG = 'javadoc'
  SOURCES_CONFIG = 'sources'
  DEFAULT_CONFIG = 'default'

  def __init__(self, get_db):
    super(IvyWriter, self).__init__(
        get_db,
        IvyUtils.IVY_TEMPLATE_PATH,
        template_package_name=IvyUtils.IVY_TEMPLATE_PACKAGE_NAME)

  def templateargs(self, target_jar, confs=None):
    return dict(lib=target_jar.extend(
        publications=set(confs) if confs else set(),
        overrides=None))

  def _jardep(self, jar, transitive=True, configurations='default'):
    return TemplateData(
        org=jar.org,
        module=jar.name,
        version=jar.rev,
        mutable=False,
        force=jar.force,
        excludes=[self.create_exclude(exclude) for exclude in jar.excludes],
        transitive=transitive,
        artifacts=jar.artifacts,
        configurations=configurations)

  def jardep(self, jar):
    return self._jardep(jar,
        transitive=jar.transitive,
        configurations=jar._configurations)

  def internaldep(self, jar_dependency, dep=None, configurations=None):
    return self._jardep(jar_dependency, configurations=configurations)


def coordinate(org, name, rev=None):
  return '%s#%s;%s' % (org, name, rev) if rev else '%s#%s' % (org, name)


def jar_coordinate(jar, rev=None):
  return coordinate(jar.org, jar.name, rev or jar.rev)


def target_internal_dependencies(target):
  return filter(lambda tgt: isinstance(tgt, Jarable), target.dependencies)


class JarPublish(JarTask, ScmPublish):
  """Publish jars to a maven repository.

  At a high-level, pants uses `Apache Ivy <http://ant.apache.org/ivy/>`_ to
  publish artifacts to Maven-style repositories. Pants performs prerequisite
  tasks like compiling, creating jars, and generating ``pom.xml`` files then
  invokes Ivy to actually publish the artifacts, so publishing is largely
  configured in ``ivysettings.xml``. ``BUILD`` and ``pants.ini`` files
  primarily provide linkage between publishable targets and the
  Ivy ``resolvers`` used to publish them.

  The following target types are publishable: :ref:`bdict_java_library`,
  :ref:`bdict_scala_library`, :ref:`bdict_java_thrift_library`,
  :ref:`bdict_annotation_processor`.
  Targets to publish and their dependencies must be publishable target
  types and specify the ``provides`` argument. One exception is
  :ref:`bdict_jar`\s - pants will generate a pom file that
  depends on the already-published jar.

  Example usage: ::

     # By default pants will perform a dry-run.
     ./pants goal clean-all publish src/java/com/twitter/mybird

     # Actually publish.
     ./pants goal clean-all publish src/java/com/twitter/mybird --no-publish-dryrun

  Please see ``./pants goal publish -h`` for a detailed description of all
  publishing options.

  Publishing can be configured in ``pants.ini`` as follows.

  ``jar-publish`` section:

  * ``repos`` - Required dictionary of settings for repos that may be pushed to.
  * ``ivy_jvmargs`` - Optional list of JVM command-line args when invoking Ivy.
  * ``restrict_push_branches`` - Optional list of branches to restrict publishing to.

  Example pants.ini jar-publish repos dictionary: ::

     repos = {
       # repository target name is paired with this key
       'myrepo': {
         # ivysettings.xml resolver to use for publishing
         'resolver': 'maven.twttr.com',
         # ivy configurations to publish
         'confs': ['default', 'sources', 'javadoc'],
         # address of a Credentials target to use when publishing
         'auth': 'address/of/credentials:target',
         # help message if unable to initialize the Credentials target.
         'help': 'Please check your credentials and try again.',
       },
     }

  Additionally the ``ivy`` section ``ivy_settings`` property specifies which
  Ivy settings file to use when publishing is required.
  """

  _CONFIG_SECTION = 'jar-publish'

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(JarPublish, cls).setup_parser(option_group, args, mkflag)

    # TODO(John Sirois): Support a preview mode that outputs a file with entries like:
    # artifact id:
    # revision:
    # publish: (true|false)
    # changelog:
    #
    # Allow re-running this goal with the file as input to support forcing an arbitrary set of
    # revisions and supply of hand edited changelogs.

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
    option_group.add_option(flag, action='append', dest='jar_publish_override',
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

  def __init__(self, *args, **kwargs):
    super(JarPublish, self).__init__(*args, **kwargs)
    ScmPublish.__init__(self, get_scm(),
                        self.context.config.getlist(self._CONFIG_SECTION, 'restrict_push_branches'))
    self.cachedir = os.path.join(self.workdir, 'cache')

    self._jvmargs = self.context.config.getlist(self._CONFIG_SECTION, 'ivy_jvmargs', default=[])

    if self.context.options.jar_publish_local:
      local_repo = dict(
        resolver='publish_local',
        path=os.path.abspath(os.path.expanduser(self.context.options.jar_publish_local)),
        confs=['default'],
        auth=None
      )
      self.repos = defaultdict(lambda: local_repo)
      self.commit = False
      self.snapshot = self.context.options.jar_publish_local_snapshot
    else:
      self.repos = self.context.config.getdict(self._CONFIG_SECTION, 'repos')
      if not self.repos:
        raise TaskError("This repo is not configured to publish externally! Please configure per\n"
                        "http://pantsbuild.github.io/publish.html#authenticating-to-the-artifact-repository,\n"
                        "or re-run with the '--publish-local' flag.")
      for repo, data in self.repos.items():
        auth = data.get('auth')
        if auth:
          credentials = self.context.resolve(auth).next()
          user = credentials.username(data['resolver'])
          password = credentials.password(data['resolver'])
          self.context.log.debug('Found auth for repo=%s user=%s' % (repo, user))
          self.repos[repo]['username'] = user
          self.repos[repo]['password'] = password
      self.commit = self.context.options.jar_publish_commit
      self.snapshot = False

    self.ivycp = self.context.config.getlist('ivy', 'classpath')

    self.dryrun = self.context.options.jar_publish_dryrun
    self.transitive = self.context.options.jar_publish_transitive
    self.force = self.context.options.jar_publish_force

    def parse_jarcoordinate(coordinate):
      components = coordinate.split('#', 1)
      if len(components) == 2:
        org, name = components
        return org, name
      else:
        try:
          address = Address.parse(get_buildroot(), coordinate)  # TODO: This is broken.
          try:
            target = Target.get(address)
            if not target:
              siblings = Target.get_all_addresses(address.build_file)
              prompt = 'did you mean' if len(siblings) == 1 else 'maybe you meant one of these'
              raise TaskError('%s => %s?:\n    %s' % (address, prompt,
                                                      '\n    '.join(str(a) for a in siblings)))
            if not target.is_exported:
              raise TaskError('%s is not an exported target' % coordinate)
            return target.provides.org, target.provides.name
          except (ImportError, SyntaxError, TypeError):
            raise TaskError('Failed to parse %s' % address.build_file.relpath)
        except IOError:
          raise TaskError('No BUILD file could be found at %s' % coordinate)

    self.overrides = {}
    if self.context.options.jar_publish_override:
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

      self.overrides.update(parse_override(o) for o in self.context.options.jar_publish_override)

    self.restart_at = None
    if self.context.options.jar_publish_restart_at:
      self.restart_at = parse_jarcoordinate(self.context.options.jar_publish_restart_at)

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def prepare(self, round_manager):
    round_manager.require('jars')
    round_manager.require('javadoc')
    round_manager.require('scaladoc')

  def execute(self):
    self.check_clean_master(commit=(not self.dryrun and self.commit))

    exported_targets = self.exported_targets()
    self.check_targets(exported_targets)

    pushdbs = {}

    def get_db(tgt):
      # TODO(tdesai) Handle resource type in get_db.
      if tgt.provides is None:
        raise TaskError('trying to publish target %r which does not provide an artifact' % tgt)
      dbfile = tgt.provides.repo.push_db
      result = pushdbs.get(dbfile)
      if not result:
        db = PushDb.load(dbfile)
        repo = self.repos[tgt.provides.repo.name]
        result = (db, dbfile, repo)
        pushdbs[dbfile] = result
      return result

    def get_pushdb(tgt):
      return get_db(tgt)[0]

    def fingerprint_internal(tgt):
      pushdb, _, _ = get_db(tgt)
      _, _, _, fingerprint = pushdb.as_jar_with_version(tgt)
      return fingerprint or '0.0.0'

    def stage_artifact(tgt, jar, version, changelog, confs=None, artifact_ext=''):
      def path(name=None, suffix='', extension='jar'):
        return self.artifact_path(jar, version, name=name, suffix=suffix, extension=extension,
                                  artifact_ext=artifact_ext)

      with safe_open(path(suffix='-CHANGELOG', extension='txt'), 'w') as changelog_file:
        changelog_file.write(changelog)
      ivyxml = path(name='ivy', extension='xml')

      IvyWriter(get_pushdb).write(tgt, ivyxml, confs=confs)
      PomWriter(get_pushdb).write(tgt, path(extension='pom'))

      return ivyxml

    def copy_artifact(tgt, jar, version, typename, suffix='', artifact_ext=''):
      genmap = self.context.products.get(typename)
      for basedir, jars in genmap.get(tgt).items():
        for artifact in jars:
          path = self.artifact_path(jar, version, suffix=suffix, artifact_ext=artifact_ext)
          safe_mkdir(os.path.dirname(path))
          shutil.copy(os.path.join(basedir, artifact), path)

    def stage_artifacts(tgt, jar, version, changelog):
      copy_artifact(tgt, jar, version, typename='jars')
      self.create_source_jar(tgt, jar, version)
      doc_jar = self.create_doc_jar(tgt, jar, version)

      confs = set(repo['confs'])
      confs.add(IvyWriter.SOURCES_CONFIG)
      if doc_jar:
        confs.add(IvyWriter.JAVADOC_CONFIG)
      return stage_artifact(tgt, jar, version, changelog, confs)

    if self.overrides:
      print('Publishing with revision overrides:\n  %s' % '\n  '.join(
        '%s=%s' % (coordinate(org, name), rev) for (org, name), rev in self.overrides.items()
      ))

    head_sha = self.scm.commit_id

    safe_rmtree(self.workdir)
    published = []
    skip = (self.restart_at is not None)
    for target in exported_targets:
      pushdb, dbfile, repo = get_db(target)
      jar, semver, sha, fingerprint = pushdb.as_jar_with_version(target)

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
        stage_artifacts(target, jar, (newver if self.force else semver).version(), changelog)
      elif skip:
        print('Skipping %s to resume at %s' % (
          jar_coordinate(jar, (newver if self.force else semver).version()),
          coordinate(self.restart_at[0], self.restart_at[1])
        ))
        stage_artifacts(target, jar, semver.version(), changelog)
      else:
        if not self.dryrun:
          # Confirm push looks good
          if no_changes:
            print(changelog)
          else:
            print('\nChanges for %s since %s @ %s:\n\n%s' % (
              coordinate(jar.org, jar.name), semver.version(), sha, changelog
            ))
          if os.isatty(sys.stdin.fileno()):
            push = raw_input('Publish %s with revision %s ? [y|N] ' % (
              coordinate(jar.org, jar.name), newver.version()
            ))
            print('\n')
            if push.strip().lower() != 'y':
              raise TaskError('User aborted push')

        pushdb.set_version(target, newver, head_sha, newfingerprint)
        ivyxml = stage_artifacts(target, jar, newver.version(), changelog)

        if self.dryrun:
          print('Skipping publish of %s in test mode.' % jar_coordinate(jar, newver.version()))
        else:
          resolver = repo['resolver']
          path = repo.get('path')

          # Get authentication for the publish repo if needed
          jvm_args = self._jvmargs
          if repo.get('auth'):
            user = repo.get('username')
            password = repo.get('password')
            if user and password:
              jvm_args.append('-Dlogin=%s' % user)
              jvm_args.append('-Dpassword=%s' % password)
            else:
              raise TaskError('Unable to publish to %s. %s' %
                              (repo['resolver'], repo.get('help', '')))

          # Do the publish
          def publish(ivyxml_path):
            try:
              ivy = Bootstrapper.default_ivy()
            except Bootstrapper.Error as e:
              raise TaskError('Failed to push %s! %s' % (jar_coordinate(jar, newver.version()), e))

            ivysettings = self.generate_ivysettings(ivy, published, publish_local=path)
            args = [
              '-settings', ivysettings,
              '-ivy', ivyxml_path,
              '-deliverto', '%s/[organisation]/[module]/ivy-[revision].xml' % self.workdir,
              '-publish', resolver,
              '-publishpattern', '%s/[organisation]/[module]/'
                                 '[artifact]-[revision](-[classifier]).[ext]' % self.workdir,
              '-revision', newver.version(),
              '-m2compatible',
            ]

            if LogOptions.stderr_log_level() == logging.DEBUG:
              args.append('-verbose')

            if self.snapshot:
              args.append('-overwrite')

            try:
              ivy.execute(jvm_options=jvm_args, args=args,
                          workunit_factory=self.context.new_workunit, workunit_name='jar-publish')
            except Ivy.Error as e:
              raise TaskError('Failed to push %s! %s' % (jar_coordinate(jar, newver.version()), e))

          publish(ivyxml)

          if self.commit:
            org = jar.org
            name = jar.name
            rev = newver.version()
            args = dict(
              org=org,
              name=name,
              rev=rev,
              coordinate=coordinate(org, name, rev),
              user=getpass.getuser(),
              cause='with forced revision' if (org, name) in self.overrides else '(autoinc)'
            )

            pushdb.dump(dbfile)
            self.commit_push(coordinate(org, name, rev))
            self.scm.refresh()
            self.scm.tag('%(org)s-%(name)s-%(rev)s' % args,
                         message='Publish of %(coordinate)s initiated by %(user)s %(cause)s' % args)

  def artifact_path(self, jar, version, name=None, suffix='', extension='jar', artifact_ext=''):
    return os.path.join(self.workdir, jar.org, jar.name + artifact_ext,
                        '%s%s-%s%s.%s' % ((name or jar.name),
                                          artifact_ext if name != 'ivy' else '',
                                          version,
                                          suffix,
                                          extension))

  def check_targets(self, targets):
    invalid = defaultdict(lambda: defaultdict(set))
    derived_by_target = dict()

    def collect(publish_target, walked_target):
      derived_by_target[walked_target.derived_from] = walked_target
      if not walked_target.has_sources() or not walked_target.sources_relative_to_buildroot():
        invalid[publish_target][walked_target].add('No sources.')
      if not walked_target.is_exported:
        invalid[publish_target][walked_target].add('Does not provide an artifact.')

    for target in targets:
      target.walk(functools.partial(collect, target), predicate=lambda t: isinstance(t, Jarable))

    # When walking the graph of a publishable target, we may encounter families of sibling targets
    # that form a derivation chain.  As long as one of these siblings is publishable, we can
    # proceed and publish a valid graph.
    # TODO(John Sirois): This does not actually handle derivation chains longer than 2 with the
    # exported item in the most derived position - fix this.
    for publish_target, invalid_targets in list(invalid.items()):
      for invalid_target, reasons in list(invalid_targets.items()):
        derived_target = derived_by_target[invalid_target]
        if derived_target not in invalid_targets:
          invalid_targets.pop(invalid_target)
      if not invalid_targets:
        invalid.pop(publish_target)

    if invalid:
      msg = list()

      def first_address(pair):
        first, _ = pair
        return str(first.address)

      for publish_target, invalid_targets in sorted(invalid.items(), key=first_address):
        msg.append('\n  Cannot publish %s due to:' % publish_target.address)
        for invalid_target, reasons in sorted(invalid_targets.items(), key=first_address):
          for reason in sorted(reasons):
            msg.append('\n    %s - %s' % (invalid_target.address, reason))

      raise TaskError('The following errors must be resolved to publish.%s' % ''.join(msg))

  def exported_targets(self):
    candidates = set()
    if self.transitive:
      candidates.update(self.context.targets())
    else:
      candidates.update(self.context.target_roots)

      def get_synthetic(lang, target):
        mappings = self.context.products.get(lang).get(target)
        if mappings:
          for key, generated in mappings.items():
            for synthetic in generated:
              yield synthetic

      # Handle the case where a code gen target is in the listed roots and the thus the publishable
      # target is a synthetic twin generated by a code gen task upstream.
      for candidate in self.context.target_roots:
        candidates.update(get_synthetic('java', candidate))
        candidates.update(get_synthetic('scala', candidate))

    def exportable(tgt):
      return tgt in candidates and tgt.is_exported

    return OrderedSet(filter(exportable,
                             reversed(sort_targets(filter(exportable, candidates)))))

  def fingerprint(self, target, fingerprint_internal):
    sha = hashlib.sha1()
    sha.update(target.invalidation_hash())

    # TODO(Tejal Desai): pantsbuild/pants/65: Remove java_sources attribute for ScalaLibrary
    if isinstance(target, ScalaLibrary):
      for java_source in sorted(target.java_sources):
        sha.update(java_source.invalidation_hash())

    # TODO(John Sirois): handle resources

    for jarsig in sorted([jar_coordinate(j) for j in target.jar_dependencies if j.rev]):
      sha.update(jarsig)

    # TODO(tdesai) Handle resource type in get_db.
    internal_dependencies = sorted(target_internal_dependencies(target), key=lambda t: t.id)
    for internal_target in internal_dependencies:
      fingerprint = fingerprint_internal(internal_target)
      sha.update(fingerprint)

    return sha.hexdigest()

  def changelog(self, target, sha):
    return self.scm.changelog(from_commit=sha,
                              files=target.sources_relative_to_buildroot())

  def generate_ivysettings(self, ivy, publishedjars, publish_local=None):
    if ivy.ivy_settings is None:
      raise TaskError('A custom ivysettings.xml with writeable resolvers is required for'
                      'publishing, but none was configured.')
    template_relpath = os.path.join('templates', 'jar_publish', 'ivysettings.mustache')
    template = pkgutil.get_data(__name__, template_relpath)
    with safe_open(os.path.join(self.workdir, 'ivysettings.xml'), 'w') as wrapper:
      generator = Generator(template,
                            ivysettings=ivy.ivy_settings,
                            dir=self.workdir,
                            cachedir=self.cachedir,
                            published=[TemplateData(org=jar.org, name=jar.name)
                                       for jar in publishedjars],
                            publish_local=publish_local)
      generator.write(wrapper)
      return wrapper.name

  def create_source_jar(self, target, open_jar, version):
    # TODO(Tejal Desai) pantsbuild/pants/65: Avoid creating 2 jars with java sources for a
    # scala_library with java_sources. Currently publish fails fast if scala_library owning
    # java sources pointed by java_library target also provides an artifact. However, jar_create
    # ends up creating 2 jars one scala and other java both including the java_sources.

    def abs_and_relative_sources(target):
      abs_source_root = os.path.join(get_buildroot(), target.target_base)
      for source in target.sources_relative_to_source_root():
        yield os.path.join(abs_source_root, source), source

    jar_path = self.artifact_path(open_jar, version, suffix='-sources')
    with self.open_jar(jar_path, overwrite=True, compressed=True) as open_jar:
      for abs_source, rel_source in abs_and_relative_sources(target):
        open_jar.write(abs_source, rel_source)

      # TODO(Tejal Desai): pantsbuild/pants/65 Remove java_sources attribute for ScalaLibrary
      if isinstance(target, ScalaLibrary):
        for java_source_target in target.java_sources:
          for abs_source, rel_source in abs_and_relative_sources(java_source_target):
            open_jar.write(abs_source, rel_source)

      if target.has_resources:
        for resource_target in target.resources:
          for abs_source, rel_source in abs_and_relative_sources(resource_target):
            open_jar.write(abs_source, rel_source)

    return jar_path

  def create_doc_jar(self, target, open_jar, version):
    javadoc = self.context.products.get('javadoc').get(target)
    scaladoc = self.context.products.get('scaladoc').get(target)
    if javadoc or scaladoc:
      jar_path = self.artifact_path(open_jar, version, suffix='-javadoc')
      with self.open_jar(jar_path, overwrite=True, compressed=True) as open_jar:
        def add_docs(docs):
          if docs:
            for basedir, doc_files in docs.items():
              for doc_file in doc_files:
                open_jar.write(os.path.join(basedir, doc_file), doc_file)

        add_docs(javadoc)
        add_docs(scaladoc)
      return jar_path
    else:
      return None
