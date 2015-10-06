# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import getpass
import hashlib
import os
import pkgutil
import shutil
import sys
from collections import OrderedDict, defaultdict, namedtuple
from copy import copy

from twitter.common.collections import OrderedSet
from twitter.common.config import Properties

from pants.backend.core.tasks.scm_publish import Namedver, ScmPublishMixin, Semver
from pants.backend.jvm.ossrh_publication_metadata import OSSRHPublicationMetadata
from pants.backend.jvm.targets.jarable import Jarable
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.jar_task import JarTask
from pants.base.address import Address
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot, get_scm
from pants.base.build_file import BuildFile
from pants.base.exceptions import TaskError
from pants.base.generator import Generator, TemplateData
from pants.build_graph.build_file_parser import BuildFileParser
from pants.build_graph.build_graph import sort_targets
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy import Ivy
from pants.option.custom_types import dict_option, list_option
from pants.util.dirutil import safe_mkdir, safe_open, safe_rmtree
from pants.util.strutil import ensure_text


_TEMPLATES_RELPATH = os.path.join('templates', 'jar_publish')


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
      return '<{}, {}, {}, {}, {}, {}>'.format(
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
    jar_dep, exported = target.get_artifact_info()
    if not exported:
      raise ValueError

    def key(prefix):
      return '{}.{}%{}'.format(prefix, jar_dep.org, jar_dep.name)

    def getter(prefix, default=None):
      return self._props.get(key(prefix), default)

    def setter(prefix, value):
      self._props[key(prefix)] = value

    return getter, setter

  def dump(self, path):
    """Saves the pushdb as a properties file to the given path."""
    with open(path, 'w') as props:
      Properties.dump(self._props, props)


class PomWriter(object):
  def __init__(self, get_db, tag):
    self._get_db = get_db
    self._tag = tag

  def write(self, target, path):
    dependencies = OrderedDict()
    for internal_dep in target_internal_dependencies(target):
      jar = self._as_versioned_jar(internal_dep)
      key = (jar.org, jar.name)
      dependencies[key] = self._internaldep(jar, internal_dep)

    for jar in target.jar_dependencies:
      jardep = self._jardep(jar)
      if jardep:
        key = (jar.org, jar.name, jar.classifier)
        dependencies[key] = jardep

    target_jar = self._internaldep(self._as_versioned_jar(target), target)
    if target_jar:
      target_jar = target_jar.extend(dependencies=dependencies.values())

    template_relpath = os.path.join(_TEMPLATES_RELPATH, 'pom.mustache')
    template_text = pkgutil.get_data(__name__, template_relpath)
    generator = Generator(template_text, project=target_jar)
    with safe_open(path, 'w') as output:
      generator.write(output)

  def _as_versioned_jar(self, internal_target):
    """Fetches the jar representation of the given target, and applies the latest pushdb version."""
    jar, _ = internal_target.get_artifact_info()
    pushdb_entry = self._get_db(internal_target).get_entry(internal_target)
    jar.rev = pushdb_entry.version().version()
    return jar

  def _internaldep(self, jar_dependency, target):
    template_data = self._jardep(jar_dependency)
    if isinstance(target.provides.publication_metadata, OSSRHPublicationMetadata):
      pom = target.provides.publication_metadata

      # Forming the project name from the coordinates like this is acceptable as a fallback when
      # the user supplies no project name.
      # See: http://central.sonatype.org/pages/requirements.html#project-name-description-and-url
      name = pom.name or '{}:{}'.format(jar_dependency.org, jar_dependency.name)

      template_data = template_data.extend(name=name,
                                           description=pom.description,
                                           url=pom.url,
                                           licenses=pom.licenses,
                                           scm=pom.scm.tagged(self._tag),
                                           developers=pom.developers)
    return template_data

  def _jardep(self, jar):
    return TemplateData(
      classifier=jar.classifier,
      artifact_id=jar.name,
      group_id=jar.org,
      version=jar.rev,
      scope='compile',
      excludes=[TemplateData(org=exclude.org, name=exclude.name)
                for exclude in jar.excludes if exclude.name])


def coordinate(org, name, rev=None):
  return '{}#{};{}'.format(org, name, rev) if rev else '{}#{}'.format(org, name)


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


class JarPublish(ScmPublishMixin, JarTask):
  """Publish jars to a maven repository.

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
     ./pants clean-all publish src/java/com/twitter/mybird

     # Actually publish.
     ./pants clean-all publish src/java/com/twitter/mybird --no-publish-dryrun

  Please see ``./pants publish -h`` for a detailed description of all
  publishing options.

  Publishing can be configured with the following options:

  * ``--repos`` - Required dictionary of settings for repos that may be pushed to.
  * ``--jvm-options`` - Optional list of JVM command-line args when invoking Ivy.
  * ``--restrict-push-branches`` - Optional list of branches to restrict publishing to.

  Example repos dictionary: ::

     repos = {
       # repository target name is paired with this key
       'myrepo': {
         # ivysettings.xml resolver to use for publishing
         'resolver': 'maven.example.com',
         # address of a Credentials target to use when publishing
         'auth': 'address/of/credentials:target',
         # help message if unable to initialize the Credentials target.
         'help': 'Please check your credentials and try again.',
       },
     }
  """

  class Publication(namedtuple('Publication', ['name', 'classifier', 'ext'])):
    """Represents an artifact publication.

    There will be at least 2 of these for any given published coordinate - a pom, and at least one
    other artifact.
    """

  @classmethod
  def register_options(cls, register):
    super(JarPublish, cls).register_options(register)

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
    register('--jvm-options', advanced=True, type=list_option,
             help='Use these jvm options when running Ivy.')
    register('--repos', advanced=True, type=dict_option,
             help='Settings for repositories that can be pushed to. See '
                  'https://pantsbuild.github.io/publish.html for details.')
    register('--publish-extras', advanced=True, type=dict_option,
             help='Extra products to publish. See '
                  'https://pantsbuild.github.io/dev_tasks_publish_extras.html for details.')
    register('--individual-plugins', advanced=True, default=False, action='store_true',
             help='Extra products to publish as a individual artifact.')
    register('--push-postscript', advanced=True, default=None,
             help='A post-script to add to pushdb commit messages and push tag commit messages.')
    register('--changelog', default=True, action='store_true',
             help='A changelog.txt file will be created and printed to the console for each '
                  'artifact published')

  @classmethod
  def prepare(cls, options, round_manager):
    super(JarPublish, cls).prepare(options, round_manager)
    round_manager.require('jars')
    round_manager.require('javadoc')
    round_manager.require('scaladoc')

  def __init__(self, *args, **kwargs):
    super(JarPublish, self).__init__(*args, **kwargs)
    self.cachedir = os.path.join(self.workdir, 'cache')

    self._jvm_options = self.get_options().jvm_options

    self.scm = get_scm()
    self.log = self.context.log

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
        raise TaskError(
          "This repo is not configured to publish externally! Please configure per\n"
          "http://pantsbuild.github.io/publish.html#authenticating-to-the-artifact-repository,\n"
          "or re-run with the '--publish-local' flag.")
      for repo, data in self.repos.items():
        auth = data.get('auth')
        if auth:
          credentials = next(iter(self.context.resolve(auth)))
          user = credentials.username(data['resolver'])
          password = credentials.password(data['resolver'])
          self.context.log.debug('Found auth for repo={} user={}'.format(repo, user))
          self.repos[repo]['username'] = user
          self.repos[repo]['password'] = password
      self.commit = self.get_options().commit
      self.push_postscript = self.get_options().push_postscript or ''
      self.local_snapshot = False

    self.named_snapshot = self.get_options().named_snapshot
    if self.named_snapshot:
      self.named_snapshot = Namedver.parse(self.named_snapshot)

    self.dryrun = self.get_options().dryrun
    self.transitive = self.get_options().transitive
    self.force = self.get_options().force
    self.publish_changelog = self.get_options().changelog

    def parse_jarcoordinate(coordinate):
      components = coordinate.split('#', 1)
      if len(components) == 2:
        org, name = components
        return org, name
      else:
        spec = components[0]
        address = Address.parse(spec)
        try:
          self.context.build_graph.inject_address_closure(address)
          target = self.context.build_graph.get_target(address)
          if not target:
            siblings = self.context.address_mapper.addresses_in_spec_path(address.spec_path)
            prompt = 'did you mean' if len(siblings) == 1 else 'maybe you meant one of these'
            raise TaskError('{} => {}?:\n    {}'.format(address, prompt,
                                                        '\n    '.join(str(a) for a in siblings)))
          if not target.is_exported:
            raise TaskError('{} is not an exported target'.format(coordinate))
          return target.provides.org, target.provides.name
        except (BuildFile.BuildFileError,
                BuildFileParser.BuildFileParserError,
                AddressLookupError) as e:
          raise TaskError('{message}\n  Problem identifying target at {spec}'
                          .format(message=e, spec=spec))

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
            raise TaskError('Invalid version {}: {}'.format(rev, e))
          return parse_jarcoordinate(coordinate), rev
        except ValueError:
          raise TaskError('Invalid override: {}'.format(override))

      self.overrides.update(parse_override(o) for o in self.get_options().override)

    self.restart_at = None
    if self.get_options().restart_at:
      self.restart_at = parse_jarcoordinate(self.get_options().restart_at)

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
    push = raw_input('\nPublish {} with revision {} ? [y|N] '.format(
      coord, version
    ))
    print('\n')
    return push.strip().lower() == 'y'

  def _copy_artifact(self, tgt, jar, version, typename, suffix='', extension='jar',
                     artifact_ext='', override_name=None):
    """Copy the products for a target into the artifact path for the jar/version"""
    genmap = self.context.products.get(typename)
    product_mapping = genmap.get(tgt)
    if product_mapping is None:
      raise ValueError("No product mapping in {} for {}. "
                       "You may need to run some other task first".format(typename, tgt))
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
      # No need to copy here, as this list isn't modified by the caller.
      return self._jvm_options

    # Create a copy of the options, so that the modification is appropriately transient.
    jvm_options = copy(self._jvm_options)
    user = repo.get('username')
    password = repo.get('password')
    if user and password:
      jvm_options.append('-Dlogin={}'.format(user))
      jvm_options.append('-Dpassword={}'.format(password))
    else:
      raise TaskError('Unable to publish to {}. {}'
                      .format(repo.get('resolver'), repo.get('help', '')))
    return jvm_options

  def publish(self, publications, jar, entry, repo, published):
    """Run ivy to publish a jar.  ivyxml_path is the path to the ivy file; published
    is a list of jars published so far (including this one). entry is a pushdb entry."""

    try:
      ivy = Bootstrapper.default_ivy()
    except Bootstrapper.Error as e:
      raise TaskError('Failed to push {0}! {1}'.format(pushdb_coordinate(jar, entry), e))

    path = repo.get('path')
    ivysettings = self.generate_ivysettings(ivy, published, publish_local=path)

    version = entry.version().version()
    ivyxml = self.generate_ivy(jar, version, publications)

    resolver = repo['resolver']
    args = [
      '-settings', ivysettings,
      '-ivy', ivyxml,

      # Without this setting, the ivy.xml is delivered to the CWD, littering the workspace.  We
      # don't need the ivy.xml, so just give it path under the workdir we won't use.
      '-deliverto', ivyxml + '.unused',

      '-publish', resolver,
      '-publishpattern', '{}/[organisation]/[module]/'
                         '[artifact]-[revision](-[classifier]).[ext]'.format(self.workdir),
      '-revision', version,
      '-m2compatible',
    ]

    # TODO(John Sirois): global logging options should be hidden behind some sort of log manager
    # that we can:
    # a.) obtain a handle to (dependency injection or manual plumbing)
    # b.) query for log detail, ie: `if log_manager.is_verbose:`
    if self.get_options().level == 'debug':
      args.append('-verbose')

    if self.local_snapshot:
      args.append('-overwrite')

    try:
      jvm_options = self._ivy_jvm_options(repo)
      ivy.execute(jvm_options=jvm_options, args=args,
                  workunit_factory=self.context.new_workunit, workunit_name='ivy-publish')
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
        raise TaskError('trying to publish target {!r} which does not provide an artifact'.format(tgt))
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

    def stage_artifacts(tgt, jar, version, tag, changelog):
      publications = OrderedSet()

      # TODO Remove this once we fix https://github.com/pantsbuild/pants/issues/1229
      if (not self.context.products.get('jars').has(tgt) and
          not self.get_options().individual_plugins):
        raise TaskError('Expected to find a primary artifact for {} but there was no jar for it.'
                        .format(tgt.address.reference()))

      # TODO Remove this guard once we fix https://github.com/pantsbuild/pants/issues/1229, there
      # should always be a primary artifact.
      if self.context.products.get('jars').has(tgt):
        self._copy_artifact(tgt, jar, version, typename='jars')
        publications.add(self.Publication(name=jar.name, classifier=None, ext='jar'))

        self.create_source_jar(tgt, jar, version)
        publications.add(self.Publication(name=jar.name, classifier='sources', ext='jar'))

        # don't request docs unless they are available for all transitive targets
        # TODO: doc products should be checked by an independent jar'ing task, and
        # conditionally enabled; see https://github.com/pantsbuild/pants/issues/568
        doc_jar = self.create_doc_jar(tgt, jar, version)
        if doc_jar:
          publications.add(self.Publication(name=jar.name, classifier='javadoc', ext='jar'))

        if self.publish_changelog:
          changelog_path = self.artifact_path(jar, version, suffix='-CHANGELOG', extension='txt')
          with safe_open(changelog_path, 'wb') as changelog_file:
            changelog_file.write(changelog.encode('utf-8'))
          publications.add(self.Publication(name=jar.name, classifier='CHANGELOG', ext='txt'))

      # Process any extra jars that might have been previously generated for this target, or a
      # target that it was derived from.
      for extra_product, extra_config in (self.get_options().publish_extras or {}).items():
        override_name = jar.name
        if 'override_name' in extra_config:
          # If the supplied string has a '{target_provides_name}' in it, replace it with the
          # current jar name. If not, the string will be taken verbatim.
          override_name = extra_config['override_name'].format(target_provides_name=jar.name)

        classifier = None
        suffix = ''
        if 'classifier' in extra_config:
          classifier = extra_config['classifier']
          suffix = "-{0}".format(classifier)

        extension = extra_config.get('extension', 'jar')

        extra_pub = self.Publication(name=override_name, classifier=classifier, ext=extension)

        # A lot of flexibility is allowed in parameterizing the extra artifact, ensure those
        # parameters lead to a unique publication.
        # TODO(John Sirois): Check this much earlier.
        if extra_pub in publications:
          raise TaskError("publish_extra for '{0}' must override one of name, classifier or "
                          "extension with a non-default value.".format(extra_product))

        # Build a list of targets to check. This list will consist of the current target, plus the
        # entire derived_from chain.
        target_list = [tgt]
        target = tgt
        while target.derived_from != target:
          target_list.append(target.derived_from)
          target = target.derived_from
        for cur_tgt in target_list:
          if self.context.products.get(extra_product).has(cur_tgt):
            self._copy_artifact(cur_tgt, jar, version, typename=extra_product, suffix=suffix,
                                extension=extension, override_name=override_name)
            publications.add(extra_pub)

      pom_path = self.artifact_path(jar, version, extension='pom')
      PomWriter(get_pushdb, tag).write(tgt, path=pom_path)
      return publications

    if self.overrides:
      print('\nPublishing with revision overrides:')
      for (org, name), rev in self.overrides.items():
        print('{0}={1}'.format(coordinate(org, name), rev))

    head_sha = self.scm.commit_id

    safe_rmtree(self.workdir)
    published = []
    skip = (self.restart_at is not None)
    for target in exported_targets:
      pushdb, dbfile, repo = get_db(target)
      oldentry = pushdb.get_entry(target)

      # the jar version is ignored here, since it is overridden below with the new entry
      jar, _ = target.get_artifact_info()
      published.append(jar)

      if skip and (jar.org, jar.name) == self.restart_at:
        skip = False
      # select the next version: either a named version, or semver via the pushdb/overrides
      if self.named_snapshot:
        newentry = oldentry.with_named_ver(self.named_snapshot)
      else:
        override = self.overrides.get((jar.org, jar.name))
        sem_ver = override if override else oldentry.sem_ver.bump()
        if self.local_snapshot:
          sem_ver = sem_ver.make_snapshot()

        if sem_ver <= oldentry.sem_ver:
          raise TaskError('Requested version {} must be greater than the current version {}'.format(
            sem_ver, oldentry.sem_ver
          ))
        newentry = oldentry.with_sem_ver(sem_ver)

      newfingerprint = self.fingerprint(target, fingerprint_internal)
      newentry = newentry.with_sha_and_fingerprint(head_sha, newfingerprint)
      no_changes = newentry.fingerprint == oldentry.fingerprint

      changelog = ''
      if self.publish_changelog:
        if no_changes:
          changelog = 'No changes for {0} - forced push.\n'.format(pushdb_coordinate(jar, oldentry))
        else:
          changelog = self.changelog(target, oldentry.sha) or 'Direct dependencies changed.\n'

      org = jar.org
      name = jar.name
      rev = newentry.version().version()
      tag_name = '{org}-{name}-{rev}'.format(org=org, name=name, rev=rev) if self.commit else None

      if no_changes and not self.force:
        print('No changes for {0}'.format(pushdb_coordinate(jar, oldentry)))
        stage_artifacts(target, jar, oldentry.version().version(), tag_name, changelog)
      elif skip:
        print('Skipping {} to resume at {}'.format(
          jar_coordinate(jar, (newentry.version() if self.force else oldentry.version()).version()),
          coordinate(self.restart_at[0], self.restart_at[1])
        ))
        stage_artifacts(target, jar, oldentry.version().version(), tag_name, changelog)
      else:
        if not self.dryrun:
          # Confirm push looks good
          if self.publish_changelog:
            if no_changes:
              print(changelog)
            else:
              # The changelog may contain non-ascii text, but the print function can, under certain
              # circumstances, incorrectly detect the output encoding to be ascii and thus blow up
              # on non-ascii changelog characters.  Here we explicitly control the encoding to avoid
              # the print function's mis-interpretation.
              # TODO(John Sirois): Consider introducing a pants/util `print_safe` helper for this.
              message = '\nChanges for {} since {} @ {}:\n\n{}\n'.format(
                  coordinate(jar.org, jar.name), oldentry.version(), oldentry.sha, changelog)
              # The stdout encoding can be detected as None when running without a tty (common in
              # tests), in which case we want to force encoding with a unicode-supporting codec.
              encoding = sys.stdout.encoding or 'utf-8'
              sys.stdout.write(message.encode(encoding))
          if not self.confirm_push(coordinate(jar.org, jar.name), newentry.version()):
            raise TaskError('User aborted push')

        pushdb.set_entry(target, newentry)
        publications = stage_artifacts(target, jar, rev, tag_name, changelog)

        if self.dryrun:
          print('Skipping publish of {0} in test mode.'.format(pushdb_coordinate(jar, newentry)))
        else:
          self.publish(publications, jar=jar, entry=newentry, repo=repo, published=published)

          if self.commit:
            coord = coordinate(org, name, rev)

            pushdb.dump(dbfile)

            self.publish_pushdb_changes_to_remote_scm(
              pushdb_file=dbfile,
              coordinate=coord,
              tag_name=tag_name,
              tag_message='Publish of {coordinate} initiated by {user} {cause}'.format(
                coordinate=coord,
                user=getpass.getuser(),
                cause='with forced revision' if (org, name) in self.overrides else '(autoinc)',
              ),
              postscript=self.push_postscript
            )

  def artifact_path(self, jar, version, name=None, suffix='', extension='jar', artifact_ext=''):
    return os.path.join(self.workdir, jar.org, jar.name + artifact_ext,
                        '{}{}-{}{}.{}'.format((name or jar.name),
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
        msg.append('\n  Cannot publish {} due to:'.format(publish_target.address))
        for invalid_target, reasons in sorted(invalid_targets.items(), key=first_address):
          for reason in sorted(reasons):
            msg.append('\n    {} - {}'.format(invalid_target.address, reason))

      raise TaskError('The following errors must be resolved to publish.{}'.format(''.join(msg)))

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

      # Handle the case where a code gen target is in the listed roots and thus the publishable
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
    return ensure_text(self.scm.changelog(from_commit=sha,
                                          files=target.sources_relative_to_buildroot()))

  def fetch_ivysettings(self, ivy):
    if self.get_options().ivy_settings:
      return self.get_options().ivy_settings
    elif ivy.ivy_settings is None:
      raise TaskError('An ivysettings.xml with writeable resolvers is required for publishing, '
                      'but none was configured.')
    else:
      return ivy.ivy_settings

  def generate_ivysettings(self, ivy, publishedjars, publish_local=None):
    template_relpath = os.path.join(_TEMPLATES_RELPATH, 'ivysettings.mustache')
    template_text = pkgutil.get_data(__name__, template_relpath)

    published = [TemplateData(org=jar.org, name=jar.name) for jar in publishedjars]

    generator = Generator(template_text,
                          ivysettings=self.fetch_ivysettings(ivy),
                          dir=self.workdir,
                          cachedir=self.cachedir,
                          published=published,
                          publish_local=publish_local)

    with safe_open(os.path.join(self.workdir, 'ivysettings.xml'), 'w') as wrapper:
      generator.write(wrapper)
      return wrapper.name

  def generate_ivy(self, jar, version, publications):
    template_relpath = os.path.join(_TEMPLATES_RELPATH, 'ivy.mustache')
    template_text = pkgutil.get_data(__name__, template_relpath)

    pubs = [TemplateData(name=None if p.name == jar.name else p.name,
                         classifier=p.classifier,
                         ext=None if p.ext == 'jar' else p.ext) for p in publications]

    generator = Generator(template_text,
                          org=jar.org,
                          name=jar.name,
                          rev=version,
                          publications=pubs)

    with safe_open(os.path.join(self.workdir, 'ivy.xml'), 'w') as ivyxml:
      generator.write(ivyxml)
      return ivyxml.name

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

  def _java_doc(self, target):
    return self.context.products.get('javadoc').get(target)

  def _scala_doc(self, target):
    return self.context.products.get('scaladoc').get(target)

  def create_doc_jar(self, target, open_jar, version):
    """Returns a doc jar if either scala or java docs are available for the given target."""
    javadoc = self._java_doc(target)
    scaladoc = self._scala_doc(target)
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
