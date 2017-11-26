# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import json
import logging
import os
import shutil
from collections import defaultdict

from twitter.common.collections import OrderedDict

from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.subsystems.jar_dependency_management import JarDependencyManagement
from pants.backend.jvm.subsystems.resolve_subsystem import JvmResolveSubsystem
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.java.jar.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.net.http.fetcher import Fetcher
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_mkdir, touch
from pants.util.process_handler import subprocess


logger = logging.getLogger(__name__)


class CoursierError(Exception):
  pass


class CoursierResolve(NailgunTask):
  """
  Experimental 3rdparty resolver using coursier.

  # TODO(wisechengyi):
  # 1. Add conf support
  # 2. Pinned artifact support
  # 3. forced version
  """

  @classmethod
  def subsystem_dependencies(cls):
    return super(CoursierResolve, cls).subsystem_dependencies() + (JvmResolveSubsystem.scoped(cls),)

  @classmethod
  def product_types(cls):
    return ['compile_classpath']

  @classmethod
  def prepare(cls, options, round_manager):
    super(CoursierResolve, cls).prepare(options, round_manager)
    round_manager.require_data('java')
    round_manager.require_data('scala')

  @classmethod
  def register_options(cls, register):
    super(CoursierResolve, cls).register_options(register)
    register('--fetch-options', type=list, fingerprint=True,
             help='Additional options to pass to coursier fetch. See `coursier fetch --help`')
    register('--bootstrap-jar-url', advanced=True, default='https://dl.dropboxusercontent.com/s/nc5hxyhsvwp9k4j/coursier-cli.jar?dl=0',
             help='Location to download a bootstrap version of Coursier.')

  def execute(self):
    """Resolves the specified confs for the configured targets and returns an iterator over
    tuples of (conf, jar path).
    """

    jvm_resolve_subsystem = JvmResolveSubsystem.scoped_instance(self)
    if jvm_resolve_subsystem.get_options().resolver != 'coursier':
      return

    coursier_jar = self._bootstrap_coursier(self.get_options().bootstrap_jar_url)

    executor = self.create_java_executor()
    classpath_products = self.context.products.get_data('compile_classpath',
                                                        init_func=ClasspathProducts.init_func(
                                                          self.get_options().pants_workdir))

    confs = ['default']
    targets_by_sets = JarDependencyManagement.global_instance().targets_by_artifact_set(self.context.targets())
    results = []
    for artifact_set, target_subset in targets_by_sets.items():
      self.resolve(coursier_jar,
                   target_subset,
                   classpath_products,
                   workunit_factory=self.context.new_workunit,
                   pants_workdir=self.context.options.for_scope(GLOBAL_SCOPE).pants_workdir,
                   coursier_fetch_options=self.get_options().fetch_options)

  def resolve(self, coursier_jar, targets, compile_classpath, workunit_factory, pants_workdir, coursier_fetch_options, pinned_artifacts=None):
    manager = JarDependencyManagement.global_instance()

    jar_targets = manager.targets_by_artifact_set(targets)

    for artifact_set, target_subset in jar_targets.items():
      jars, global_excludes = IvyUtils.calculate_classpath(target_subset)

      jars_by_key = OrderedDict()
      for jar in jars:
        jars_for_the_key = jars_by_key.setdefault((jar.org, jar.name), [])
        jars_for_the_key.append(jar)

      jars_to_resolve = []
      exclude_args = set()
      for k, v in jars_by_key.items():
        for jar in v:
          jars_to_resolve.append(jar)
          for ex in jar.excludes:
            # `--` means exclude. See --soft-exclude-file in coursier
            ex_arg = "{}:{}--{}:{}".format(jar.org, jar.name, ex.org, ex.name)
            exclude_args.add(ex_arg)

      # Prepare coursier args
      exe = 'dist/coursier-cli.jar'
      output_fn = 'output.json'
      coursier_cache_path = os.path.join(self.get_options().pants_bootstrapdir, 'coursier')
      pants_jar_path_base = os.path.join(pants_workdir, 'coursier')

      common_args = [
                      # 'bash',
                     # exe,
                     'fetch',
                     '--cache', coursier_cache_path,
                     '--json-output-file', output_fn] + coursier_fetch_options

      def construct_classifier_to_jar(jars):
        product = defaultdict(list)
        for j in jars:
          product[j.coordinate.classifier or ''].append(j)
        return product

      classifier_to_jars = construct_classifier_to_jar(jars_to_resolve)

      # Coursier calls need to be divided by classifier because coursier treats classifier option globally.
      for classifier, jars in classifier_to_jars.items():

        cmd_args = list(common_args)
        if classifier:
          cmd_args.extend(['--classifier', classifier])

        for j in jars:
          if j.intransitive:
            cmd_args.append('--intransitive')
          cmd_args.append(j.coordinate.simple_coord)

        if exclude_args:
          exclude_file = 'excludes.txt'
          with open(exclude_file, 'w') as f:
            f.write('\n'.join(exclude_args).encode('utf8'))

          cmd_args.append('--soft-exclude-file')
          cmd_args.append(exclude_file)

        for ex in global_excludes:
          cmd_args.append('-E')
          cmd_args.append('{}:{}'.format(ex.org, ex.name))

        cmd_str = ' '.join(cmd_args)
        logger.info(cmd_str)

        try:
          # with workunit_factory(name='coursier', labels=[WorkUnitLabel.TOOL], cmd=cmd_str) as workunit:

          return_code = self.runjava(
            classpath=[coursier_jar],
            main='coursier.cli.Coursier',
            args=cmd_args,
            # jvm_options=self.get_options().jvm_options,
            # to let stdout/err through, but don't print tool's label.
            workunit_labels=[WorkUnitLabel.COMPILER, WorkUnitLabel.SUPPRESS_LABEL])

          # return_code = subprocess.call(cmd_args,
          #                               stdout=workunit.output('stdout'),
          #                               stderr=workunit.output('stderr'))

          # workunit.set_outcome(WorkUnit.FAILURE if return_code else WorkUnit.SUCCESS)

          with open(output_fn) as f:
            result = json.loads(f.read())

          if return_code:
            raise TaskError('The coursier process exited non-zero: {0}'.format(return_code))

        except subprocess.CalledProcessError as e:
          raise CoursierError(e)

        else:
          flattened_resolution = self._flatten_resolution_by_root(result)
          files_by_coord = self._map_coord_to_resolved_jars(result, coursier_cache_path, pants_jar_path_base)

          for t in targets:
            if isinstance(t, JarLibrary):

              def get_transitive_resolved_jars(my_simple_coord, resolved_jars):
                transitive_jar_path_for_coord = []
                if my_simple_coord in flattened_resolution:
                  for c in [my_simple_coord] + flattened_resolution[my_simple_coord]:
                    transitive_jar_path_for_coord.extend(resolved_jars[c])

                return transitive_jar_path_for_coord

              for jar in t.jar_dependencies:
                simple_coord_candidate = jar.coordinate.simple_coord
                final_simple_coord = None
                if simple_coord_candidate in files_by_coord:
                  final_simple_coord = simple_coord_candidate
                elif simple_coord_candidate in result['conflict_resolution']:
                  final_simple_coord = result['conflict_resolution'][simple_coord_candidate]

                if final_simple_coord:
                  transitive_resolved_jars = get_transitive_resolved_jars(final_simple_coord, files_by_coord)
                  if transitive_resolved_jars:
                    compile_classpath.add_jars_for_targets([t], 'default', transitive_resolved_jars)

          # This return value is not important
          # return flattened_resolution

  @classmethod
  def _flatten_resolution_by_root(cls, result):
    """
    Flatten the resolution by root dependencies. If we want to resolve X and Y, and X->A->B, and Y -> C,
    the result will be {X: [A, B], Y: [C]}

    :param result: see a nested dict capturing the resolution.
    :return: a flattened view with the top artifact as the roots.
    """

    def flat_walk(dep_map):
      for art in dep_map:
        for x in flat_walk(art['dependencies']):
          yield x
        yield art['coord']

    flat_result = defaultdict(list)

    for artifact in result['dependencies']:
      flat_result[artifact['coord']].extend(flat_walk(artifact['dependencies']))

    return flat_result

  @classmethod
  def _map_coord_to_resolved_jars(cls, result, coursier_cache_path, pants_jar_path_base):
    """
    Flatten the file paths corresponding to the coordinate from the nested json.

    :param result: coursier json output
    :param coursier_cache_path: coursier cache location
    :param pants_jar_path_base: location under pants workdir to store the symlink to the coursier cache
    :return: a map form simple coordinate to a set of resolved jars.
    """

    final_result = defaultdict(set)

    def walk(dep_map):
      for art in dep_map:

        for classifier, jar_path in art['files']:
          simple_coord = art['coord']
          coord = cls.to_m2_coord(simple_coord, classifier)
          pants_path = os.path.join(pants_jar_path_base, os.path.relpath(jar_path, coursier_cache_path))

          if not os.path.exists(pants_path):
            safe_mkdir(os.path.dirname(pants_path))
            os.symlink(jar_path, pants_path)

          resolved_jar = ResolvedJar(coord,
                                     cache_path=jar_path,
                                     pants_path=pants_path)
          final_result[simple_coord].add(resolved_jar)

        walk(art['dependencies'])

    walk(result['dependencies'])
    return final_result

  @classmethod
  def to_m2_coord(cls, coord_str, classifier=''):
    # TODO: currently assuming everything is a jar and no classifier
    return M2Coordinate.from_string(coord_str + ':{}:jar'.format(classifier))

  def _bootstrap_coursier(self, bootstrap_url):

    coursier_bootstrap_dir = os.path.join(self.get_options().pants_bootstrapdir,
                                     'tools', 'jvm', 'coursier')

    bootstrap_jar_path = os.path.join(coursier_bootstrap_dir, 'coursier.jar')

    # options = self._ivy_subsystem.get_options()
    if not os.path.exists(bootstrap_jar_path):
      with temporary_file() as bootstrap_jar:
        fetcher = Fetcher(get_buildroot())
        checksummer = fetcher.ChecksumListener(digest=hashlib.sha1())
        try:
          logger.info('\nDownloading {}'.format(bootstrap_url))
          # TODO: Capture the stdout of the fetcher, instead of letting it output
          # to the console directly.
          fetcher.download(bootstrap_url,
                           listener=fetcher.ProgressListener().wrap(checksummer),
                           path_or_fd=bootstrap_jar,
                           timeout_secs=2)
          logger.info('sha1: {}'.format(checksummer.checksum))
          bootstrap_jar.close()
          touch(bootstrap_jar_path)
          shutil.move(bootstrap_jar.name, bootstrap_jar_path)
        except fetcher.Error as e:
          raise self.Error('Problem fetching the ivy bootstrap jar! {}'.format(e))

    return bootstrap_jar_path
