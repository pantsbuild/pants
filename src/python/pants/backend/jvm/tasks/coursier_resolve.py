# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import logging
import os

from pants.util.process_handler import subprocess
# import subprocess
from collections import defaultdict

from twitter.common.collections import OrderedDict

from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.subsystems.jar_dependency_management import JarDependencyManagement, PinnedJarArtifactSet
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.java.jar.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.util.dirutil import safe_mkdir

logger = logging.getLogger(__name__)


class CoursierError(Exception):
  pass


class CoursierResolve:
  @classmethod
  def resolve(cls, targets, compile_classpath, workunit_factory, pants_workdir, pinned_artifacts=None, excludes=[]):
    manager = JarDependencyManagement.global_instance()

    jar_targets = manager.targets_by_artifact_set(targets)

    assert len(jar_targets) == 1

    for artifact_set, target_subset in jar_targets.items():
      jars, global_excludes = IvyUtils.calculate_classpath(target_subset)

    t_subset = target_subset

    org = IvyUtils.INTERNAL_ORG_NAME
    # name = resolve_hash_name
    #
    # extra_configurations = [conf for conf in confs if conf and conf != 'default']

    jars_by_key = OrderedDict()
    for jar in jars:
      jars = jars_by_key.setdefault((jar.org, jar.name), [])
      jars.append(jar)

    artifact_set = PinnedJarArtifactSet(pinned_artifacts)  # Copy, because we're modifying it.
    for jars in jars_by_key.values():
      for i, dep in enumerate(jars):
        direct_coord = M2Coordinate.create(dep)
        managed_coord = artifact_set[direct_coord]
        if direct_coord.rev != managed_coord.rev:
          # It may be necessary to actually change the version number of the jar we want to resolve
          # here, because overrides do not apply directly (they are exclusively transitive). This is
          # actually a good thing, because it gives us more control over what happens.
          coord = manager.resolve_version_conflict(managed_coord, direct_coord, force=dep.force)
          jars[i] = dep.copy(rev=coord.rev)
        elif dep.force:
          # If this dependency is marked as 'force' and there is no version conflict, use the normal
          # pants behavior for 'force'.
          artifact_set.put(direct_coord)

    dependencies = [IvyUtils._generate_jar_template(jars) for jars in jars_by_key.values()]

    # As it turns out force is not transitive - it only works for dependencies pants knows about
    # directly (declared in BUILD files - present in generated ivy.xml). The user-level ivy docs
    # don't make this clear [1], but the source code docs do (see isForce docs) [2]. I was able to
    # edit the generated ivy.xml and use the override feature [3] though and that does work
    # transitively as you'd hope.
    #
    # [1] http://ant.apache.org/ivy/history/2.3.0/settings/conflict-managers.html
    # [2] https://svn.apache.org/repos/asf/ant/ivy/core/branches/2.3.0/
    #     src/java/org/apache/ivy/core/module/descriptor/DependencyDescriptor.java
    # [3] http://ant.apache.org/ivy/history/2.3.0/ivyfile/override.html
    overrides = [IvyUtils._generate_override_template(_coord) for _coord in artifact_set]

    excludes = [IvyUtils._generate_exclude_template(exclude) for exclude in excludes]

    resolve_args = []
    exclude_args = set()
    for k, v in jars_by_key.items():
      for jar in v:
        resolve_args.append(jar.coordinate)
        for ex in jar.excludes:
          ex_arg = "{}:{}".format(ex.org, ex.name)
          exclude_args.add(ex_arg)

    def get_m2_id(coord):
      return ':'.join([coord.org, coord.name, coord.rev])

    # Prepare cousier args
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

    def construct_classifier_to_coordinates(list_of_coords):
      product = defaultdict(list)
      for my_coord in list_of_coords:
        product[my_coord.classifier or ''].append(my_coord)
      return product

    classifier_to_coordinates = construct_classifier_to_coordinates(resolve_args)
    for classifier, coords in classifier_to_coordinates.items():

      cmd_args = list(common_args)
      if classifier:
        cmd_args.extend(['--classifier', classifier])

      cmd_args.extend(get_m2_id(x) for x in coords)

      # Add org:artifact to exclude
      for x in exclude_args:
        cmd_args.append('-E')
        cmd_args.append(x)

      cmd_str = ' '.join(cmd_args)
      logger.info(cmd_str)

      try:
        with workunit_factory(name='coursier', labels=[WorkUnitLabel.TOOL], cmd=cmd_str) as workunit:
          # ret = runner.run(stdout=workunit.output('stdout'), stderr=workunit.output('stderr'))
          # output = subprocess.check_output(cmd_args, stderr=workunit.output('stderr'))

          return_code = subprocess.call(cmd_args,
                                        stdout=workunit.output('stdout'),
                                        stderr=workunit.output('stderr'))

          workunit.set_outcome(WorkUnit.FAILURE if return_code else WorkUnit.SUCCESS)

          with open(output_fn) as f:
            read = f.read()
            # print(read)
            result = json.loads(read)

          # with open(workunit.output('stdout')._io.name) as f:
          #   stdout = f.read()

          if return_code:
            raise TaskError('The coursier process exited non-zero: {0}'.format(return_code))

      except subprocess.CalledProcessError as e:
        raise CoursierError()

      else:
        flattened_resolution = cls.flatten_resolution_by_root(result)
        files_by_coord = cls.files_by_coord(result, coursier_cache_path, pants_jar_path_base)

        # resolved_jars = cls.parse_jar_paths(coursier_cache_path, pants_jar_path_base, stdout)

        for t in targets:
          if isinstance(t, JarLibrary):

            def get_transitive_resolved_jars(my_simple_coord, resolved_jars):
              # TODO: currently resolved jars matching the simple coord will be collected,
              # need to only collect the ones that are matching exactly.
              transitive_jar_path_for_coord = []
              if my_simple_coord in flattened_resolution:
                for c in [my_simple_coord] + flattened_resolution[my_simple_coord]:
                  transitive_jar_path_for_coord.extend(resolved_jars[c])

              return transitive_jar_path_for_coord

            for jar in t.jar_dependencies:
              simple_coord = jar.coordinate.simple_coord
              if simple_coord in files_by_coord:
                transitive_resolved_jars = get_transitive_resolved_jars(simple_coord, files_by_coord)
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
  def flatten_resolution_by_root(cls, result):
    """
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
  def files_by_coord(cls, result, coursier_cache_path, pants_jar_path_base):

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
