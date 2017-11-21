# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import logging
import os
# import subprocess
from collections import defaultdict

from twitter.common.collections import OrderedDict

from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.subsystems.jar_dependency_management import JarDependencyManagement
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.java.jar.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.util.dirutil import safe_mkdir
from pants.util.process_handler import subprocess

logger = logging.getLogger(__name__)


class CoursierError(Exception):
  pass


class CoursierResolve:
  # TODO(wisechengyi): add conf support
  @classmethod
  def resolve(cls, targets, compile_classpath, workunit_factory, pants_workdir, pinned_artifacts=None, excludes=[]):
    manager = JarDependencyManagement.global_instance()

    jar_targets = manager.targets_by_artifact_set(targets)

    assert len(jar_targets) == 1

    for artifact_set, target_subset in jar_targets.items():
      jars, global_excludes = IvyUtils.calculate_classpath(target_subset)
    #
    # t_subset = target_subset
    #
    # org = IvyUtils.INTERNAL_ORG_NAME
    # # name = resolve_hash_name
    # #
    # # extra_configurations = [conf for conf in confs if conf and conf != 'default']

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
          ex_arg = "{}:{}--{}:{}".format(jar.org, jar.name, ex.org, ex.name)
          exclude_args.add(ex_arg)

    # Prepare coursier args
    exe = '/Users/yic/workspace/coursier_dev/cli/target/pack/bin/coursier'
    output_fn = 'output.json'
    coursier_cache_path = '/Users/yic/.cache/pants/coursier/'
    pants_jar_path_base = os.path.join(pants_workdir, 'coursier')

    common_args = ['bash',
                exe,
                'fetch',
                '-r', 'https://artifactory-ci.twitter.biz/libs-releases-local/',
                '-r', 'https://artifactory-ci.twitter.biz/repo1.maven.org',
                '-r', 'https://artifactory-ci.twitter.biz/java-virtual',
                # '-r', 'https://artifactory.twitter.biz/java-virtual',
                '--no-default', # no default repo
                '-n', '20',
                '--cache', coursier_cache_path,
                '--json-output-file', output_fn]

    def construct_classifier_to_jar(jars):
      product = defaultdict(list)
      for j in jars:
        product[j.coordinate.classifier or ''].append(j)
      return product

    classifier_to_jars = construct_classifier_to_jar(jars_to_resolve)

    # Coursier calls need to be divided by classifier because coursier treats it globally.
    for classifier, jars in classifier_to_jars.items():

      cmd_args = list(common_args)
      if classifier:
        cmd_args.extend(['--classifier', classifier])

      for j in jars:
        if j.intransitive:
          cmd_args.append('--intransitive')
        cmd_args.append(j.coordinate.simple_coord)

      exclude_file = 'excludes.txt'
      with open(exclude_file, 'w') as f:
        f.write('\n'.join(exclude_args).encode('utf8'))

      cmd_args.append('--soft-exclude-file')
      cmd_args.append(exclude_file)

      cmd_str = ' '.join(cmd_args)
      logger.info(cmd_str)

      try:
        with workunit_factory(name='coursier', labels=[WorkUnitLabel.TOOL], cmd=cmd_str) as workunit:

          return_code = subprocess.call(cmd_args,
                                        stdout=workunit.output('stdout'),
                                        stderr=workunit.output('stderr'))

          workunit.set_outcome(WorkUnit.FAILURE if return_code else WorkUnit.SUCCESS)

          with open(output_fn) as f:
            result = json.loads(f.read())

          if return_code:
            raise TaskError('The coursier process exited non-zero: {0}'.format(return_code))

      except subprocess.CalledProcessError as e:
        raise CoursierError(e)

      else:
        flattened_resolution = cls._flatten_resolution_by_root(result)
        files_by_coord = cls._map_coord_to_resolved_jars(result, coursier_cache_path, pants_jar_path_base)

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
              # else:
              #   err_msg = '{} not found in resolution or in conflict_resolution'.format(simple_coord_candidate)
              #   # logger.error(err_msg)
              #   raise TaskError(err_msg)

              if final_simple_coord:
                transitive_resolved_jars = get_transitive_resolved_jars(final_simple_coord, files_by_coord)
                if transitive_resolved_jars:
                  compile_classpath.add_jars_for_targets([t], 'default', transitive_resolved_jars)

              # classifier = jar.classifier if self._conf == 'default' else self._conf
              # jar_module_ref = IvyModuleRef(jar.org, jar.name, jar.rev, classifier, jar.ext)
              # for module_ref in self.traverse_dependency_graph(jar_module_ref, create_collection, memo):
              #   for artifact_path in self._artifacts_by_ref[module_ref.unversioned]:
              #     resolved_jars.add(to_resolved_jar(module_ref, artifact_path))

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
