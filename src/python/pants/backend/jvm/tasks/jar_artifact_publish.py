# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import getpass
import hashlib
import logging
import os
import pkgutil
import shutil
import sys
import traceback
from collections import defaultdict

from twitter.common.collections import OrderedDict
from twitter.common.config import Properties

from pants.backend.core.tasks.scm_publish import Namedver, ScmPublish, Semver
from pants.backend.jvm.targets.jarable import Jarable
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.jar_task import JarTask
from pants.base.address import Address
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot, get_scm
from pants.base.build_file import BuildFile
from pants.base.build_file_parser import BuildFileParser
from pants.base.exceptions import TaskError
from pants.base.target import Target
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy import Ivy
from pants.option.options import Options
from pants.scm.scm import Scm
from pants.util.dirutil import safe_mkdir, safe_open, safe_rmtree
from pants.util.strutil import ensure_text


class PushDb(object):
  @staticmethod
  def load(path):
    """Loads a pushdb maintained in a properties file at the given path."""
    with open(path, 'r') as props:
      properties = Properties.load(props)
      return PushDb(properties)

  class Entry(object):
    def __init__(self, sem_ver, named_ver, named_is_latest, sha, fingerprint):
      """Records the most recent push/release of an artifact.

      :param Semver sem_ver: The last semantically versioned release (or Semver(0.0.0))
      :param Namedver named_ver: The last named release of this entry (or None)
      :param boolean named_is_latest: True if named_ver is the latest, false if sem_ver is
      :param string sha: The last Git SHA (or None)
      :param string fingerprint: A unique hash for the most recent version of the target.
      """
      self.sem_ver = sem_ver
      self.named_ver = named_ver
      self.named_is_latest = named_is_latest
      self.sha = sha
      self.fingerprint = fingerprint

    def version(self):
      if self.named_is_latest:
        return self.named_ver
      else:
        return self.sem_ver

    def with_sem_ver(self, sem_ver):
      """Returns a clone of this entry with the given sem_ver marked as the latest."""
      return PushDb.Entry(sem_ver, self.named_ver, False, self.sha, self.fingerprint)

    def with_named_ver(self, named_ver):
      """Returns a clone of this entry with the given name_ver marked as the latest."""
      return PushDb.Entry(self.sem_ver, named_ver, True, self.sha, self.fingerprint)

    def with_sha_and_fingerprint(self, sha, fingerprint):
      """Returns a clone of this entry with the given sha and fingerprint."""
      return PushDb.Entry(self.sem_ver, self.named_ver, self.named_is_latest, sha, fingerprint)

    def __repr__(self):
      return '<%s, %s, %s, %s, %s, %s>' % (
        self.__class__.__name__, self.sem_ver, self.named_ver, self.named_is_latest,
        self.sha, self.fingerprint)

  def __init__(self, props=None):
    self._props = props or OrderedDict()

  def get_entry(self, target):
    """Given an internal target, return a PushDb.Entry, which might contain defaults."""
    db_get, _ = self._accessors_for_target(target)

    major = int(db_get('revision.major', '0'))
    minor = int(db_get('revision.minor', '0'))
    patch = int(db_get('revision.patch', '0'))
    snapshot = str(db_get('revision.snapshot', 'false')).lower() == 'true'
    named_version = db_get('revision.named_version', None)
    named_is_latest = str(db_get('revision.named_is_latest', 'false')).lower() == 'true'
    sha = db_get('revision.sha', None)
    fingerprint = db_get('revision.fingerprint', None)
    sem_ver = Semver(major, minor, patch, snapshot=snapshot)
    named_ver = Namedver(named_version) if named_version else None
    return self.Entry(sem_ver, named_ver, named_is_latest, sha, fingerprint)

  def set_entry(self, target, pushdb_entry):
    pe = pushdb_entry
    _, db_set = self._accessors_for_target(target)
    db_set('revision.major', pe.sem_ver.major)
    db_set('revision.minor', pe.sem_ver.minor)
    db_set('revision.patch', pe.sem_ver.patch)
    db_set('revision.snapshot', str(pe.sem_ver.snapshot).lower())
    if pe.named_ver:
      db_set('revision.named_version', pe.named_ver.version())
    db_set('revision.named_is_latest', str(pe.named_is_latest).lower())
    db_set('revision.sha', pe.sha)
    db_set('revision.fingerprint', pe.fingerprint)

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

    return getter, setter

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

  def write(self, target, path, confs=None, extra_confs=None):
    # TODO(John Sirois): a dict is used here to de-dup codegen targets which have both the original
    # codegen target - say java_thrift_library - and the synthetic generated target (java_library)
    # Consider reworking codegen tasks to add removal of the original codegen targets when rewriting
    # the graph
    dependencies = OrderedDict()
    internal_codegen = {}
    configurations = set(confs or [])
    for dep in target_internal_dependencies(target):
      jar = self._as_versioned_jar(dep)
      dependencies[(jar.org, jar.name)] = self.internaldep(jar, dep)
      if dep.is_codegen:
        internal_codegen[jar.name] = jar.name
    for jar in target.jar_dependencies:
      if jar.rev:
        dependencies[(jar.org, jar.name)] = self.jardep(jar)
        configurations |= set(jar._configurations)

    target_jar = self.internaldep(self._as_versioned_jar(target),
                                  configurations=list(configurations))
    target_jar = target_jar.extend(dependencies=dependencies.values())

    template_kwargs = self.templateargs(target_jar, confs, extra_confs)
    with safe_open(path, 'w') as output:
      template = pkgutil.get_data(self.template_package_name, self.template_relpath)
      Generator(template, **template_kwargs).write(output)

  def templateargs(self, target_jar, confs=None, extra_confs=None):
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

  def _as_versioned_jar(self, internal_target):
    """Fetches the jar representation of the given target, and applies the latest pushdb version."""
    jar, _, _ = internal_target.get_artifact_info()
    pushdb_entry = self.get_db(internal_target).get_entry(internal_target)
    jar.rev = pushdb_entry.version().version()
    return jar

  def jardep(self, jar_dependency):
    """Subclasses must return a template data for the given external jar dependency."""
    raise NotImplementedError()


def coordinate(org, name, rev=None):
	return '%s#%s;%s' % (org, name, rev) if rev else '%s#%s' % (org, name)


def jar_coordinate(jar, rev=None):
	return coordinate(jar.org, jar.name, rev or jar.rev)


def pushdb_coordinate(jar, entry):
	return jar_coordinate(jar, rev=entry.version().version())


def target_internal_dependencies(target):
	"""Returns internal Jarable dependencies that were "directly" declared.

	Directly declared deps are those that are explicitly listed in the definition of a
	target, rather than being depended on transitively. But in order to walk through
	aggregator targets such as `target`, `dependencies`, or `jar_library`, this recursively
	descends the dep graph and stops at Jarable instances."""
	for dep in target.dependencies:
		if isinstance(dep, Jarable):
			yield dep
		else:
			for childdep in target_internal_dependencies(dep):
				yield childdep


class JarArtifactPublish(JarTask, ScmPublish):
  """Publish jar artifact to a maven repository.

  At a high-level, pants uses `Apache Ivy <http://ant.apache.org/ivy/>`_ to
  publish artifacts to Maven-style repositories. Pants performs prerequisite
  tasks like compiling, creating jars, and generating ``pom.xml`` files then
  invokes Ivy to actually publish the artifacts, so publishing is largely
  configured in ``ivysettings.xml``. ``BUILD`` and ``pants.ini`` files
  primarily provide linkage between publishable targets and the
  Ivy ``resolvers`` used to publish them.

  The following target types are publishable:
  `java_library <build_dictionary.html#java_library>`_,
  `scala_library <build_dictionary.html#scala_library>`_,
  `java_thrift_library <build_dictionary.html#java_thrift_library>`_,
  `annotation_processor <build_dictionary.html#annotation_processor>`_.
  Targets to publish and their dependencies must be publishable target
  types and specify the ``provides`` argument. One exception is
  `jar <build_dictionary.html#jar>`_\s - pants will generate a pom file that
  depends on the already-published jar.

  Example usage: ::

     # By default pants will perform a dry-run.
     ./pants goal clean-all publish src/java/com/twitter/mybird

     # Actually publish.
     ./pants goal clean-all publish src/java/com/twitter/mybird --no-publish-dryrun

  Please see ``./pants goal publish -h`` for a detailed description of all
  publishing options.

  Publishing can be configured with the following options:

  * ``repos`` - Required dictionary of settings for repos that may be pushed to.
  * ``--jvm-options`` - Optional list of JVM command-line args when invoking Ivy.
  * ``--restrict-push-branches`` - Optional list of branches to restrict publishing to.

  Example repos dictionary: ::

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
  """

  _SCM_PUSH_ATTEMPTS = 5

  @classmethod
  def register_options(cls, register):
    super(JarArtifactPublish, cls).register_options(register)

    # TODO(John Sirois): Support a preview mode that outputs a file with entries like:
    # artifact id:
    # revision:
    # publish: (true|false)
    # changelog:
    #
    # Allow re-running this goal with the file as input to support forcing an arbitrary set of
    # revisions and supply of hand edited changelogs.

    register('--dryrun', default=True, action='store_true',
             help='Run through a push without actually pushing artifacts, editing publish dbs or '
                  'otherwise writing data')
    register('--commit', default=True, action='store_true',
             help='Commit the push db. Turn off for local testing.')
    register('--local', metavar='<PATH>',
             help='Publish jars to a maven repository on the local filesystem at this path.')
    register('--scm-push-attempts', type=int, default=cls._SCM_PUSH_ATTEMPTS,
             help='Try pushing the pushdb to the SCM this many times before aborting.')
    register('--local-snapshot', default=True, action='store_true',
             help='If --local is specified, publishes jars with -SNAPSHOT revision suffixes.')
    register('--named-snapshot', default=None,
             help='Publish all artifacts with the given snapshot name, replacing their version. '
                  'This is not Semantic Versioning compatible, but is easier to consume in cases '
                  'where many artifacts must align.')
    register('--transitive', default=True, action='store_true',
             help='Publish the specified targets and all their internal dependencies transitively.')
    register('--force', default=False, action='store_true',
             help='Force pushing jars even if there have been no changes since the last push.')
    register('--override', action='append',
             help='Specifies a published jar revision override in the form: '
                  '([org]#[name]|[target spec])=[new revision] '
                  'For example, to specify 2 overrides: '
                  '--override=com.foo.bar#baz=0.1.2  --override=src/java/com/foo/bar/qux=1.0.0')
    register('--restart-at',
             help='Restart a fail push at the given jar.  Jars can be identified by '
                  'maven coordinate [org]#[name] or target. '
                  'For example: --restart-at=com.twitter.common#quantity '
                  'Or: --restart-at=src/java/com/twitter/common/base')
    register('--ivy_settings', advanced=True, default=None,
             help='Specify a custom ivysettings.xml file to be used when publishing.')
    register('--restrict-push-branches', advanced=True, type=Options.list,
             help='Allow pushes only from one of these branches.')
    register('--jvm-options', advanced=True, type=Options.list,
             help='Use these jvm options when running Ivy.')
    register('--repos', advanced=True, type=Options.dict,
             help='Settings for repositories that can be pushed to. See '
                'https://pantsbuild.github.io/publish.html for details.')
    register('--publish-extras', advanced=True, type=Options.dict,
             help='Extra products to publish. See '
                'https://pantsbuild.github.io/dev_tasks_publish_extras.html for details.')

  def __init__(self, *args, **kwargs):
    super(JarArtifactPublish, self).__init__(*args, **kwargs)
    ScmPublish.__init__(self, get_scm(), self.get_options().restrict_push_branches)
    self.cachedir = os.path.join(self.workdir, 'cache')

    self._jvm_options = self.get_options().jvm_options

    if self.get_options().local:
      local_repo = dict(
        resolver='publish_local',
        path=os.path.abspath(os.path.expanduser(self.get_options().local)),
        confs=['default'],
        auth=None
      )
      self.repos = defaultdict(lambda: local_repo)
      self.commit = False
      self.local_snapshot = self.get_options().local_snapshot
    else:
      self.repos = self.get_options().repos
      if not self.repos:
        raise TaskError("This repo is not configured to publish externally! Please configure per\n"
                        "http://pantsbuild.github.io/publish.html#authenticating-to-the-artifact-repository,\n"
                        "or re-run with the '--publish-local' flag.")
      for repo, data in self.repos.items():
        auth = data.get('auth')
        if auth:
          credentials = next(iter(self.context.resolve(auth)))
          user = credentials.username(data['resolver'])
          password = credentials.password(data['resolver'])
          self.context.log.debug('Found auth for repo=%s user=%s' % (repo, user))
          self.repos[repo]['username'] = user
          self.repos[repo]['password'] = password

      self.commit = self.get_options().commit
      self.local_snapshot = False

    self.named_snapshot = self.get_options().named_snapshot
    if self.named_snapshot:
      self.named_snapshot = Namedver.parse(self.named_snapshot)


    self.dryrun = self.get_options().dryrun
    self.transitive = self.get_options().transitive
    self.force = self.get_options().force

    def parse_jarcoordinate(coordinate):
      components = coordinate.split('#', 1)
      if len(components) == 2:
        org, name = components
        return org, name
      else:
        try:
          # TODO(Eric Ayers) This code is suspect.  Target.get() is a very old method and almost certainly broken.
          # Refactor to use methods from BuildGraph or BuildFileAddressMapper
          address = Address.parse(get_buildroot(), coordinate)
          target = Target.get(address)
          if not target:
            siblings = Target.get_all_addresses(address.build_file)
            prompt = 'did you mean' if len(siblings) == 1 else 'maybe you meant one of these'
            raise TaskError('%s => %s?:\n    %s' % (address, prompt,
                                                    '\n    '.join(str(a) for a in siblings)))
          if not target.is_exported:
            raise TaskError('%s is not an exported target' % coordinate)
          return target.provides.org, target.provides.name
        except (BuildFile.BuildFileError, BuildFileParser.BuildFileParserError, AddressLookupError) as e:
          raise TaskError('{message}\n  Problem with BUILD file  at {coordinate}'
                          .format(message=e, coordinate=coordinate))

    self.overrides = {}
    if self.get_options().override:
      if self.named_snapshot:
        raise TaskError('Options --named-snapshot and --override are mutually exclusive!')

      def parse_override(override):
        try:
          coordinate, rev = override.split('=', 1)
          try:
            # overrides imply semantic versioning
            rev = Semver.parse(rev)
          except ValueError as e:
            raise TaskError('Invalid version %s: %s' % (rev, e))
          return parse_jarcoordinate(coordinate), rev
        except ValueError:
          raise TaskError('Invalid override: %s' % override)

      self.overrides.update(parse_override(o) for o in self.get_options().override)

    self.restart_at = None
    if self.get_options().restart_at:
      self.restart_at = parse_jarcoordinate(self.get_options().restart_at)


  def prepare(self, round_manager):
    raise NotImplementedError('Subclasses must define exported_targets')

  def confirm_push(self, coord, version):
    """Ask the user if a push should be done for a particular version of a
       particular coordinate.   Return True if the push should be done"""
    try:
      isatty = os.isatty(sys.stdin.fileno())
    except ValueError:
      # In tests, sys.stdin might not have a fileno
      isatty = False
    if not isatty:
      return True
    artifact_name = '-'.join(coord, self.classifier) if self.classifier else coord
    push = raw_input('Publish %s with revision %s ? [y|N] ' % (
    artifact_name, version
    ))
    print('\n')
    return push.strip().lower() == 'y'

  def _copy_artifact(self, tgt, jar, version, typename, suffix='', extension='jar',
                     artifact_ext='', override_name=None):
    """Copy the products for a target into the artifact path for the jar/version"""
    genmap = self.context.products.get(typename)
    product_mapping = genmap.get(tgt)
    if product_mapping is None:
      raise ValueError("No product mapping in %s for %s. "
                       "You may need to run some other task first" % (typename, tgt))
    for basedir, jars in product_mapping.items():
      for artifact in jars:
        path = self.artifact_path(jar, version, name=override_name, suffix=suffix,
                                  extension=extension, artifact_ext=artifact_ext)
        safe_mkdir(os.path.dirname(path))
        shutil.copy(os.path.join(basedir, artifact), path)

  def _ivy_jvm_options(self, repo):
    """Get the JVM options for ivy authentication, if needed."""
    # Get authentication for the publish repo if needed.
    if not repo.get('auth'):
      return self._jvm_options

    jvm_options = self._jvm_options
    user = repo.get('username')
    password = repo.get('password')
    if user and password:
      jvm_options.append('-Dlogin=%s' % user)
      jvm_options.append('-Dpassword=%s' % password)
    else:
      raise TaskError('Unable to publish to %s. %s' %
                      (repo.get('resolver'), repo.get('help', '')))
    return jvm_options

  def publish(self, ivyxml_path, jar, entry, repo, published):
    """Run ivy to publish a jar.  ivyxml_path is the path to the ivy file; published
    is a list of jars published so far (including this one). entry is a pushdb entry."""
    jvm_options = self._ivy_jvm_options(repo)
    resolver = repo['resolver']
    path = repo.get('path')

    try:
      ivy = Bootstrapper.default_ivy()
    except Bootstrapper.Error as e:
      raise TaskError('Failed to push {0}! {1}'.format(pushdb_coordinate(jar, entry), e))

    ivysettings = self.generate_ivysettings(ivy, published, publish_local=path)
    args = [
      '-settings', ivysettings,
      '-ivy', ivyxml_path,
      '-deliverto', '%s/[organisation]/[module]/ivy-[revision].xml' % self.workdir,
      '-publish', resolver,
      '-publishpattern', '%s/[organisation]/[module]/'
                         '[artifact]-[revision](-[classifier]).[ext]' % self.workdir,
      '-revision', entry.version().version(),
      '-m2compatible',
      ]

    if self.get_options().level == 'debug':
      args.append('-verbose')

    if self.local_snapshot:
      args.append('-overwrite')

    try:
      ivy.execute(jvm_options=jvm_options, args=args,
                  workunit_factory=self.context.new_workunit, workunit_name='jar-publish')
    except Ivy.Error as e:
      raise TaskError('Failed to push {0}! {1}'.format(pushdb_coordinate(jar, entry), e))

  def execute(self):
    self.check_clean_master(commit=(not self.dryrun and self.commit))

    exported_targets = self.exported_targets()
    self.check_targets(exported_targets)

    pushdbs = {}

    def get_db(tgt):
      # TODO(tdesai) Handle resource type in get_db.
      if tgt.provides is None:
        raise TaskError('trying to publish target %r which does not provide an artifact' % tgt)
      dbfile = tgt.provides.repo.push_db(tgt)
      result = pushdbs.get(dbfile)
      if not result:
        # Create an empty pushdb if no dbfile exists.
        if (os.path.exists(dbfile)):
          db = PushDb.load(dbfile)
        else:
          safe_mkdir(os.path.dirname(dbfile))
          db = PushDb()
        try:
          repo = self.repos[tgt.provides.repo.name]
        except KeyError:
          raise TaskError('Repository {0} has no entry in the --repos option.'.format(
            tgt.provides.repo.name))
        result = (db, dbfile, repo)
        pushdbs[dbfile] = result
      return result

    def get_pushdb(tgt):
      return get_db(tgt)[0]

    def fingerprint_internal(tgt):
      pushdb = get_pushdb(tgt)
      entry = pushdb.get_entry(tgt)
      return entry.fingerprint or '0.0.0'

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
      oldentry = pushdb.get_entry(target)

      # the jar version is ignored here, since it is overridden below with the new entry
      jar, _, _ = target.get_artifact_info()
      published.append(jar)

      if skip and (jar.org, jar.name) == self.restart_at:
        skip = False

      # select the next version: either a named version, or semver via the pushdb/overrides
      if self.named_snapshot:
        newentry = oldentry.with_named_ver(self.named_snapshot)
      else:
        override = self.overrides.get((jar.org, jar.name))
        sem_ver = Semver.parse(override) if override else oldentry.sem_ver.bump()
        if self.local_snapshot:
          sem_ver = sem_ver.make_snapshot()

        if sem_ver <= oldentry.sem_ver:
          raise TaskError('Requested version %s must be greater than the current version %s' % (
            sem_ver, oldentry.sem_ver
          ))
        newentry = oldentry.with_sem_ver(sem_ver)

      newfingerprint = self.fingerprint(target, fingerprint_internal)
      newentry = newentry.with_sha_and_fingerprint(head_sha, newfingerprint)
      no_changes = newentry.fingerprint == oldentry.fingerprint

      if no_changes:
        changelog = 'No changes for {0} - forced push.\n'.format(pushdb_coordinate(jar, oldentry))
      else:
        changelog = self.changelog(target, oldentry.sha) or 'Direct dependencies changed.\n'

      confs = set(repo['confs'])

      if no_changes and not self.force:
        print('No changes for {0}'.format(pushdb_coordinate(jar, oldentry)))
        self.stage_artifacts(target, jar, oldentry.version().version(), confs, changelog)
      elif skip:
        print('Skipping %s to resume at %s' % (
          jar_coordinate(jar, (newentry.version() if self.force else oldentry.version()).version()),
          coordinate(self.restart_at[0], self.restart_at[1])
        ))
        self.stage_artifacts(target, jar, oldentry.version().version(), confs, changelog)
      else:
        if not self.dryrun:
          # Confirm push looks good
          if no_changes:
            print(changelog)
          else:
            print('\nChanges for %s since %s @ %s:\n\n%s' % (
              coordinate(jar.org, jar.name), oldentry.version(), oldentry.sha, changelog
            ))
          if not self.confirm_push(coordinate(jar.org, jar.name), newentry.version()):
            raise TaskError('User aborted push')

        pushdb.set_entry(target, newentry)
        ivyxml = self.stage_artifacts(target, jar, newentry.version().version(), confs, changelog)

        if self.dryrun:
          print('Skipping publish of {0} in test mode.'.format(pushdb_coordinate(jar, newentry)))
        else:
          self.publish(ivyxml, jar=jar, entry=newentry, repo=repo, published=published)

          if self.commit:
            org = jar.org
            name = jar.name
            rev = newentry.version().version()
            args = dict(
              org=org,
              name=name,
              rev=rev,
              coordinate=coordinate(org, name, rev),
              user=getpass.getuser(),
              cause='with forced revision' if (org, name) in self.overrides else '(autoinc)'
            )

            pushdb.dump(dbfile)
            self.commit_pushdb(coordinate(org, name, rev))
            scm_exception = None
            for attempt in range(self.get_options().scm_push_attempts):
              try:
                self.context.log.debug("Trying scm push")
                self.scm.push()
                break # success
              except Scm.RemoteException as scm_exception:
                self.context.log.debug("Scm push failed, trying to refresh")
                # This might fail in the event that there is a real conflict, throwing
                # a Scm.LocalException (in case of a rebase failure) or a Scm.RemoteException
                # in the case of a fetch failure.  We'll directly raise a local exception,
                # since we can't fix it by retrying, but if we do, we want to display the
                # remote exception that caused the refresh as well just in case the user cares.
                # Remote exceptions probably indicate network or configuration issues, so
                # we'll let them propagate
                try:
                  self.scm.refresh(leave_clean=True)
                except Scm.LocalException as local_exception:
                  exc = traceback.format_exc(scm_exception)
                  self.context.log.debug("SCM exception while pushing: %s" % exc)
                  raise local_exception

            else:
              raise scm_exception

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
    derived_by_target = defaultdict(set)

    def collect_invalid(publish_target, walked_target):
      for derived_target in walked_target.derived_from_chain:
        derived_by_target[derived_target].add(walked_target)
      if not walked_target.has_sources() or not walked_target.sources_relative_to_buildroot():
        invalid[publish_target][walked_target].add('No sources.')
      if not walked_target.is_exported:
        invalid[publish_target][walked_target].add('Does not provide a binary artifact.')

    for target in targets:
      target.walk(functools.partial(collect_invalid, target),
                  predicate=lambda t: isinstance(t, Jarable))

    # When walking the graph of a publishable target, we may encounter families of sibling targets
    # that form a derivation chain.  As long as one of these siblings is publishable, we can
    # proceed and publish a valid graph.
    for publish_target, invalid_targets in list(invalid.items()):
      for invalid_target, reasons in list(invalid_targets.items()):
        derived_from_set = derived_by_target[invalid_target]
        if derived_from_set - set(invalid_targets.keys()):
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
    raise NotImplementedError('Subclasses must define exported_targets')

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
    return ensure_text(self.scm.changelog(from_commit=sha,
                                          files=target.sources_relative_to_buildroot()))

  def generate_ivysettings(self, ivy, publishedjars, publish_local=None):
    if ivy.ivy_settings is None:
      raise TaskError('A custom ivysettings.xml with writeable resolvers is required for '
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

  def stage_artifacts(self, tgt, jar, version, changelog):
    self._copy_artifact(tgt, jar, version, typename=self.jar_product_type)
    extra_confs = []

    # Process any extra jars that might have been previously generated for this target, or a
    # target that it was derived from.
    for extra_product, extra_config in (self.get_options().publish_extras or {}).items():
      override_name = jar.name
      if 'override_name' in extra_config:
        # If the supplied string has a '{target_provides_name}' in it, replace it with the
        # current jar name. If not, the string will be taken verbatim.
        override_name = extra_config['override_name'].format(target_provides_name=jar.name)

      classifier = self.classifier
      suffix = ''
      ivy_type = self.ivy_type
      if 'classifier' in extra_config:
        classifier = extra_config['classifier']
        suffix = "-{0}".format(classifier)
        ivy_type = classifier

      extension = self.jar_extension
      if 'extension' in extra_config:
        extension = extra_config['extension']
        if ivy_type == self.ivy_type:
          ivy_type = extension

      # A lot of flexibility is allowed in naming the extra artifact. Because the name must be
      # unique, some extra logic is required to ensure that the user supplied at least one
      # non-default value (thus ensuring a uniquely-named artifact in the end).
      if override_name == jar.name and classifier == DEFAULT_CLASSIFIER and extension == DEFAULT_EXTENSION:
        raise TaskError("publish_extra for '{0}' most override one of name, classifier or "
                        "extension with a non-default value.".format(extra_product))

      ivy_tmpl_key = "publish_extra-{0}{1}{2}".format(override_name, classifier, extension)

      # Build a list of targets to check. This list will consist of the current target, plus the
      # entire derived_from chain.
      target_list = [tgt]
      target = tgt
      while target.derived_from != target:
        target_list.append(target.derived_from)
        target = target.derived_from
      for cur_tgt in target_list:
        if self.context.products.get(extra_product).has(cur_tgt):
          self._copy_artifact(cur_tgt, jar, version, typename=extra_product,
                              suffix=suffix, extension=extension,
                              override_name=override_name)
          confs.add(ivy_tmpl_key)
          # Supply extra data about this jar into the Ivy template, so that Ivy will publish it
          # to the final destination.
          extra_confs.append({'name': override_name,
                              'type': ivy_type,
                              'conf': ivy_tmpl_key,
                              'classifier': classifier,
                              'ext': extension})
    return self.stage_artifact(tgt, jar, version, changelog, confs,
                               artifact_ext=self.artifact_ext,
                               extra_confs=extra_confs)

  def stage_artifact(self, tgt, jar, version, changelog, confs=None,
                     artifact_ext='', extra_confs=None):
    def path(name=None, suffix='', extension='jar'):
      return self.artifact_path(jar, version, name=name, suffix=suffix, extension=extension,
                                artifact_ext=artifact_ext)

    with safe_open(path(suffix='-CHANGELOG', extension='txt'), 'wb') as changelog_file:
      changelog_file.write(changelog.encode('utf-8'))
    ivyxml = path(name='ivy', extension='xml')

    self.ivy_writer(self.get_pushdb).write(tgt, ivyxml, confs=confs, extra_confs=extra_confs)
    self.pom_writer(self.get_pushdb).write(tgt, path(extension='pom'))
    return ivyxml

  @property
  def ivy_type(self):
    "Returns the default product type. Subclasses can override this "
    return 'jar'
  @property
  def jar_extension(self):
    return 'jar'

  @property
  def jar_product_type(self):
    raise NotImplementedError('Subclasses must define jar product type.')

  @property
  def artifact_ext(self):
    raise NotImplementedError('Subclasses must define artifact extension for jar')
  @property
  def ivy_writer(self):
    raise NotImplementedError('Subclasses must define Ivy Dependency writer.')

  @property
  def pom_writer(self):
    raise NotImplementedError('Subclasses must define Pom Dependency Writer.')

  @property
  def classifier(self):
    raise NotImplementedError('Subclasses must define classifier for the generated jar.')
