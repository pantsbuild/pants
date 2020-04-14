# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import itertools
import json
import os
from collections import defaultdict
from urllib import parse

from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.subsystems.jar_dependency_management import (
    JarDependencyManagement,
    PinnedJarArtifactSet,
)
from pants.backend.jvm.subsystems.resolve_subsystem import JvmResolveSubsystem
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.coursier.coursier_subsystem import CoursierSubsystem
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.backend.jvm.tasks.resolve_shared import JvmResolverBase
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import FingerprintStrategy
from pants.base.workunit import WorkUnitLabel
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.java import util
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import Executor, SubprocessExecutor
from pants.java.jar.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_mkdir
from pants.util.fileutil import safe_hardlink_or_copy


class CoursierResultNotFound(Exception):
    pass


class CoursierMixin(JvmResolverBase):
    """Experimental 3rdparty resolver using coursier.

    TODO(wisechengyi):
    1. Add relative url support
    """

    RESULT_FILENAME = "result"

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("CoursierMixin", 2)]

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (
            CoursierSubsystem,
            DistributionLocator,
            JarDependencyManagement,
        )

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--allow-global-excludes",
            type=bool,
            advanced=False,
            fingerprint=True,
            default=True,
            help="Whether global excludes are allowed.",
        )
        register(
            "--report",
            type=bool,
            advanced=False,
            default=False,
            help="Show the resolve output. This would also force a resolve even if the resolve task is validated.",
        )

    @staticmethod
    def _compute_jars_to_resolve_and_pin(raw_jars, artifact_set, manager):
        """This method provides settled lists of jar dependencies and coordinates based on conflict
        management.

        :param raw_jars: a collection of `JarDependencies`
        :param artifact_set: PinnedJarArtifactSet
        :param manager: JarDependencyManagement
        :return: (list of settled `JarDependency`, set of pinned `M2Coordinate`)
        """
        if artifact_set is None:
            artifact_set = PinnedJarArtifactSet()

        untouched_pinned_artifact = {M2Coordinate.create(x) for x in artifact_set}
        jar_list = list(raw_jars)
        for i, dep in enumerate(jar_list):
            direct_coord = M2Coordinate.create(dep)
            # Portion to manage pinned jars in case of conflict
            if direct_coord in artifact_set:
                managed_coord = artifact_set[direct_coord]
                untouched_pinned_artifact.remove(managed_coord)

                if direct_coord.rev != managed_coord.rev:
                    # It may be necessary to actually change the version number of the jar we want to resolve
                    # here, because overrides do not apply directly (they are exclusively transitive). This is
                    # actually a good thing, because it gives us more control over what happens.
                    coord = manager.resolve_version_conflict(
                        managed_coord, direct_coord, force=dep.force
                    )

                    # Once a version is settled, we force it anyway
                    jar_list[i] = dep.copy(rev=coord.rev, force=True)

        return jar_list, untouched_pinned_artifact

    def resolve(self, targets, compile_classpath, sources, javadoc, executor):
        """This is the core function for coursier resolve.

        Validation strategy:

        1. All targets are going through the `invalidated` to get fingerprinted in the target level.
           No cache is fetched at this stage because it is disabled.
        2. Once each target is fingerprinted, we combine them into a `VersionedTargetSet` where they
           are fingerprinted together, because each run of 3rdparty resolve is context sensitive.

        Artifacts are stored in `VersionedTargetSet`'s results_dir, the contents are the aggregation of
        each coursier run happened within that context.

        Caching: (TODO): https://github.com/pantsbuild/pants/issues/5187
        Currently it is disabled due to absolute paths in the coursier results.

        :param targets: a collection of targets to do 3rdparty resolve against
        :param compile_classpath: classpath product that holds the resolution result. IMPORTANT: this parameter will be changed.
        :param sources: if True, fetch sources for 3rdparty
        :param javadoc: if True, fetch javadoc for 3rdparty
        :param executor: An instance of `pants.java.executor.Executor`. If None, a subprocess executor will be assigned.
        :return: n/a
        """
        manager = JarDependencyManagement.global_instance()

        jar_targets = manager.targets_by_artifact_set(targets)

        executor = executor or SubprocessExecutor(DistributionLocator.cached())
        if not isinstance(executor, Executor):
            raise ValueError(
                "The executor argument must be an Executor instance, given {} of type {}".format(
                    executor, type(executor)
                )
            )

        for artifact_set, target_subset in jar_targets.items():
            # TODO(wisechengyi): this is the only place we are using IvyUtil method, which isn't specific to ivy really.
            raw_jar_deps, global_excludes = IvyUtils.calculate_classpath(target_subset)

            # ['sources'] * False = [], ['sources'] * True = ['sources']
            confs_for_fingerprint = ["sources"] * sources + ["javadoc"] * javadoc
            fp_strategy = CoursierResolveFingerprintStrategy(confs_for_fingerprint)

            compile_classpath.add_excludes_for_targets(target_subset)

            with self.invalidated(
                target_subset,
                invalidate_dependents=False,
                silent=False,
                fingerprint_strategy=fp_strategy,
            ) as invalidation_check:

                if not invalidation_check.all_vts:
                    continue

                resolve_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)

                vt_set_results_dir = self._prepare_vts_results_dir(resolve_vts)
                pants_jar_base_dir = self._prepare_workdir()
                coursier_cache_dir = CoursierSubsystem.global_instance().get_options().cache_dir

                # If a report is requested, do not proceed with loading validated result.
                if not self.get_options().report:
                    # Check each individual target without context first
                    # If the individuals are valid, check them as a VersionedTargetSet
                    # The order of 'or' statement matters, because checking for cache is more expensive.
                    if resolve_vts.valid or (
                        self.artifact_cache_reads_enabled()
                        and len(self.check_artifact_cache([resolve_vts])[0])
                        == len(resolve_vts.targets)
                    ):
                        # Load up from the results dir
                        success = self._load_from_results_dir(
                            compile_classpath,
                            vt_set_results_dir,
                            coursier_cache_dir,
                            invalidation_check,
                            pants_jar_base_dir,
                        )
                        if success:
                            resolve_vts.update()
                            return

                jars_to_resolve, pinned_coords = self._compute_jars_to_resolve_and_pin(
                    raw_jar_deps, artifact_set, manager
                )

                results = self._get_result_from_coursier(
                    jars_to_resolve,
                    global_excludes,
                    pinned_coords,
                    coursier_cache_dir,
                    sources,
                    javadoc,
                    executor,
                )

                for conf, result_list in results.items():
                    for result in result_list:
                        self._load_json_result(
                            conf,
                            compile_classpath,
                            coursier_cache_dir,
                            invalidation_check,
                            pants_jar_base_dir,
                            result,
                            self._override_classifiers_for_conf(conf),
                        )

                self._populate_results_dir(vt_set_results_dir, results)
                resolve_vts.update()

                if self.artifact_cache_writes_enabled():
                    self.update_artifact_cache([(resolve_vts, [vt_set_results_dir])])

    def _override_classifiers_for_conf(self, conf):
        # TODO Encapsulate this in the result from coursier instead of here.
        #      https://github.com/coursier/coursier/issues/803
        if conf == "src_doc":
            return ["sources", "javadoc"]
        else:
            return None

    def _prepare_vts_results_dir(self, vts):
        """Given a `VergetTargetSet`, prepare its results dir."""
        vt_set_results_dir = os.path.join(self.versioned_workdir, "results", vts.cache_key.hash)
        safe_mkdir(vt_set_results_dir)
        return vt_set_results_dir

    def _prepare_workdir(self):
        """Prepare the location in our task workdir to store all the hardlinks to coursier cache
        dir."""
        pants_jar_base_dir = os.path.join(self.versioned_workdir, "cache")
        safe_mkdir(pants_jar_base_dir)
        return pants_jar_base_dir

    def _get_result_from_coursier(
        self,
        jars_to_resolve,
        global_excludes,
        pinned_coords,
        coursier_cache_path,
        sources,
        javadoc,
        executor,
    ):
        """Calling coursier and return the result per invocation.

        If coursier was called once for classifier '' and once for classifier 'tests', then the return value
        would be: {'default': [<first coursier output>, <second coursier output>]}

        :param jars_to_resolve: List of `JarDependency`s to resolve
        :param global_excludes: List of `M2Coordinate`s to exclude globally
        :param pinned_coords: List of `M2Coordinate`s that need to be pinned.
        :param coursier_cache_path: path to where coursier cache is stored.
        :param executor: An instance of `pants.java.executor.Executor`

        :return: The aggregation of results by conf from coursier. Each coursier call could return
        the following:
            {
              "conflict_resolution": {
                "org:name:version" (requested): "org:name:version" (reconciled)
              },
              "dependencies": [
                {
                  "coord": "orgA:nameA:versionA",
                  "file": <path>,
                  "dependencies": [ // coodinates for its transitive dependencies
                    <orgX:nameX:versionX>,
                    <orgY:nameY:versionY>,
                  ]
                },
                {
                  "coord": "orgB:nameB:jar:classifier:versionB",
                  "file": <path>,
                  "dependencies": [ // coodinates for its transitive dependencies
                    <orgX:nameX:versionX>,
                    <orgZ:nameZ:versionZ>,
                  ]
                },
                ... // more about orgX:nameX:versionX, orgY:nameY:versionY, orgZ:nameZ:versionZ
              ]
            }
        Hence the aggregation of the results will be in the following format, for example when default classifier
        and sources are fetched:
        {
          'default': [<result from coursier call with default conf with classifier X>,
                      <result from coursier call with default conf with classifier Y>],
          'src_doc': [<result from coursier call with --sources and/or --javadoc>],
        }
        """
        # Prepare coursier args
        coursier_subsystem_instance = CoursierSubsystem.global_instance()
        coursier_jar = coursier_subsystem_instance.select()

        repos = coursier_subsystem_instance.get_options().repos
        # make [repoX, repoY] -> ['-r', repoX, '-r', repoY]
        repo_args = list(itertools.chain(*list(zip(["-r"] * len(repos), repos))))
        artifact_types_arg = [
            "-A",
            ",".join(coursier_subsystem_instance.get_options().artifact_types),
        ]
        advanced_options = coursier_subsystem_instance.get_options().fetch_options
        common_args = (
            [
                "fetch",
                # Print the resolution tree
                "-t",
                "--cache",
                coursier_cache_path,
            ]
            + repo_args
            + artifact_types_arg
            + advanced_options
        )

        coursier_work_temp_dir = os.path.join(self.versioned_workdir, "tmp")
        safe_mkdir(coursier_work_temp_dir)

        results_by_conf = self._get_default_conf_results(
            common_args,
            coursier_jar,
            global_excludes,
            jars_to_resolve,
            coursier_work_temp_dir,
            pinned_coords,
            executor,
        )
        if sources or javadoc:
            non_default_conf_results = self._get_non_default_conf_results(
                common_args,
                coursier_jar,
                global_excludes,
                jars_to_resolve,
                coursier_work_temp_dir,
                pinned_coords,
                sources,
                javadoc,
                executor,
            )
            results_by_conf.update(non_default_conf_results)

        return results_by_conf

    def _get_default_conf_results(
        self,
        common_args,
        coursier_jar,
        global_excludes,
        jars_to_resolve,
        coursier_work_temp_dir,
        pinned_coords,
        executor,
    ):

        # Variable to store coursier result each run.
        results = defaultdict(list)
        with temporary_file(coursier_work_temp_dir, cleanup=False) as f:
            output_fn = f.name

        cmd_args = self._construct_cmd_args(
            jars_to_resolve,
            common_args,
            global_excludes if self.get_options().allow_global_excludes else [],
            pinned_coords,
            coursier_work_temp_dir,
            output_fn,
        )

        results["default"].append(self._call_coursier(cmd_args, coursier_jar, output_fn, executor))

        return results

    def _get_non_default_conf_results(
        self,
        common_args,
        coursier_jar,
        global_excludes,
        jars_to_resolve,
        coursier_work_temp_dir,
        pinned_coords,
        sources,
        javadoc,
        executor,
    ):
        # To prevent improper api usage during development. User should not see this anyway.
        if not sources and not javadoc:
            raise TaskError("sources or javadoc has to be True.")

        with temporary_file(coursier_work_temp_dir, cleanup=False) as f:
            output_fn = f.name

        results = defaultdict(list)

        new_pinned_coords = []
        new_jars_to_resolve = []
        special_args = []

        if not sources and not javadoc:
            new_pinned_coords = pinned_coords
            new_jars_to_resolve = jars_to_resolve
        if sources:
            special_args.append("--sources")
            new_pinned_coords.extend(c.copy(classifier="sources") for c in pinned_coords)
            new_jars_to_resolve.extend(c.copy(classifier="sources") for c in jars_to_resolve)

        if javadoc:
            special_args.append("--javadoc")
            new_pinned_coords.extend(c.copy(classifier="javadoc") for c in pinned_coords)
            new_jars_to_resolve.extend(c.copy(classifier="javadoc") for c in jars_to_resolve)

        cmd_args = self._construct_cmd_args(
            new_jars_to_resolve,
            common_args,
            global_excludes if self.get_options().allow_global_excludes else [],
            new_pinned_coords,
            coursier_work_temp_dir,
            output_fn,
        )
        cmd_args.extend(special_args)

        # sources and/or javadoc share the same conf
        results["src_doc"] = [self._call_coursier(cmd_args, coursier_jar, output_fn, executor)]
        return results

    def _call_coursier(self, cmd_args, coursier_jar, output_fn, executor):

        runner = executor.runner(
            classpath=[coursier_jar],
            main="coursier.cli.Coursier",
            jvm_options=self.get_options().jvm_options,
            args=cmd_args,
        )

        labels = [WorkUnitLabel.COMPILER] if self.get_options().report else [WorkUnitLabel.TOOL]
        return_code = util.execute_runner(runner, self.context.new_workunit, "coursier", labels)

        if return_code:
            raise TaskError(f"The coursier process exited non-zero: {return_code}")

        with open(output_fn, "r") as f:
            return json.loads(f.read())

    @staticmethod
    def _construct_cmd_args(
        jars, common_args, global_excludes, pinned_coords, coursier_workdir, json_output_path
    ):

        # Make a copy, so there is no side effect or others using `common_args`
        cmd_args = list(common_args)

        cmd_args.extend(["--json-output-file", json_output_path])

        # Dealing with intransitivity and forced versions.
        for j in jars:
            if not j.rev:
                raise TaskError(
                    'Undefined revs for jars unsupported by Coursier. "{}"'.format(
                        repr(j.coordinate).replace("M2Coordinate", "jar")
                    )
                )

            module = j.coordinate.simple_coord
            if j.coordinate.classifier:
                module += f",classifier={j.coordinate.classifier}"

            if j.get_url():
                jar_url = j.get_url()
                module += f",url={parse.quote_plus(jar_url)}"

            if j.intransitive:
                cmd_args.append("--intransitive")

            cmd_args.append(module)

            # Force requires specifying the coord again with -V
            if j.force:
                cmd_args.append("-V")
                cmd_args.append(j.coordinate.simple_coord)

        # Force pinned coordinates
        for m2coord in pinned_coords:
            cmd_args.append("-V")
            cmd_args.append(m2coord.simple_coord)

        # Local exclusions
        local_exclude_args = []
        for jar in jars:
            for ex in jar.excludes:
                # `--` means exclude. See --local-exclude-file in `coursier fetch --help`
                # If ex.name does not exist, that means the whole org needs to be excluded.
                ex_arg = f"{jar.org}:{jar.name}--{ex.org}:{ex.name or '*'}"
                local_exclude_args.append(ex_arg)

        if local_exclude_args:
            with temporary_file(coursier_workdir, cleanup=False) as f:
                exclude_file = f.name
                with open(exclude_file, "w") as ex_f:
                    ex_f.write("\n".join(local_exclude_args))

                cmd_args.append("--local-exclude-file")
                cmd_args.append(exclude_file)

        for ex in global_excludes:
            cmd_args.append("-E")
            cmd_args.append(f"{ex.org}:{ex.name or '*'}")

        return cmd_args

    def _load_json_result(
        self,
        conf,
        compile_classpath,
        coursier_cache_path,
        invalidation_check,
        pants_jar_path_base,
        result,
        override_classifiers=None,
    ):
        """Given a coursier run result, load it into compile_classpath by target.

        :param compile_classpath: `ClasspathProducts` that will be modified
        :param coursier_cache_path: cache location that is managed by coursier
        :param invalidation_check: InvalidationCheck
        :param pants_jar_path_base: location under pants workdir that contains all the hardlinks to coursier cache
        :param result: result dict converted from the json produced by one coursier run
        :return: n/a
        """
        # Parse the coursier result
        flattened_resolution = self._extract_dependencies_by_root(result)

        coord_to_resolved_jars = self._map_coord_to_resolved_jars(
            result, coursier_cache_path, pants_jar_path_base
        )

        # Construct a map from org:name to the reconciled org:name:version coordinate
        # This is used when there is won't be a conflict_resolution entry because the conflict
        # was resolved in pants.
        org_name_to_org_name_rev = {}
        for coord in coord_to_resolved_jars.keys():
            org_name_to_org_name_rev[f"{coord.org}:{coord.name}"] = coord

        jars_per_target = []

        for vt in invalidation_check.all_vts:
            t = vt.target
            jars_to_digest = []
            if isinstance(t, JarLibrary):

                def get_transitive_resolved_jars(my_coord, resolved_jars):
                    transitive_jar_path_for_coord = []
                    coord_str = str(my_coord)
                    if coord_str in flattened_resolution and my_coord in resolved_jars:
                        transitive_jar_path_for_coord.append(resolved_jars[my_coord])

                        for c in flattened_resolution[coord_str]:
                            j = resolved_jars.get(self.to_m2_coord(c))
                            if j:
                                transitive_jar_path_for_coord.append(j)

                    return transitive_jar_path_for_coord

                for jar in t.jar_dependencies:
                    # if there are override classifiers, then force use of those.
                    coord_candidates = []
                    if override_classifiers:
                        coord_candidates = [
                            jar.coordinate.copy(classifier=c) for c in override_classifiers
                        ]
                    else:
                        coord_candidates = [jar.coordinate]

                    # if conflict resolution entries, then update versions to the resolved ones.
                    if jar.coordinate.simple_coord in result["conflict_resolution"]:
                        parsed_conflict = self.to_m2_coord(
                            result["conflict_resolution"][jar.coordinate.simple_coord]
                        )
                        coord_candidates = [
                            c.copy(rev=parsed_conflict.rev) for c in coord_candidates
                        ]
                    elif f"{jar.coordinate.org}:{jar.coordinate.name}" in org_name_to_org_name_rev:
                        parsed_conflict = org_name_to_org_name_rev[
                            f"{jar.coordinate.org}:{jar.coordinate.name}"
                        ]
                        coord_candidates = [
                            c.copy(rev=parsed_conflict.rev) for c in coord_candidates
                        ]

                    for coord in coord_candidates:
                        transitive_resolved_jars = get_transitive_resolved_jars(
                            coord, coord_to_resolved_jars
                        )
                        if transitive_resolved_jars:
                            for jar in transitive_resolved_jars:
                                jars_to_digest.append(jar)

                jars_per_target.append((t, jars_to_digest))

        for target, jars_to_add in self.add_directory_digests_for_jars(jars_per_target):
            if override_classifiers is not None:
                for jar in jars_to_add:
                    compile_classpath.add_jars_for_targets(
                        [target], jar.coordinate.classifier, [jar]
                    )
            else:
                compile_classpath.add_jars_for_targets([target], conf, jars_to_add)

    def _populate_results_dir(self, vts_results_dir, results):
        with open(os.path.join(vts_results_dir, self.RESULT_FILENAME), "w") as f:
            json.dump(results, f)

    def _load_from_results_dir(
        self,
        compile_classpath,
        vts_results_dir,
        coursier_cache_path,
        invalidation_check,
        pants_jar_path_base,
    ):
        """Given vts_results_dir, load the results which can be from multiple runs of coursier into
        compile_classpath.

        :return: True if success; False if any of the classpath is not valid anymore.
        """
        result_file_path = os.path.join(vts_results_dir, self.RESULT_FILENAME)
        if not os.path.exists(result_file_path):
            return

        with open(result_file_path, "r") as f:
            results = json.load(f)
            for conf, result_list in results.items():
                for result in result_list:
                    try:
                        self._load_json_result(
                            conf,
                            compile_classpath,
                            coursier_cache_path,
                            invalidation_check,
                            pants_jar_path_base,
                            result,
                            self._override_classifiers_for_conf(conf),
                        )
                    except CoursierResultNotFound:
                        return False

        return True

    @classmethod
    def _extract_dependencies_by_root(cls, result):
        """Only extracts the transitive dependencies for the given coursier resolve. Note the
        "dependencies" field is already transitive.

        Example:
        {
          "conflict_resolution": {},
          "dependencies": [
            {
              "coord": "a",
              "dependencies": ["b", "c"]
              "file": ...
            },
            {
              "coord": "b",
              "dependencies": []
              "file": ...
            },
            {
              "coord": "c",
              "dependencies": []
              "file": ...
            }
          ]
        }

        Should return { "a": ["b", "c"], "b": [], "c": [] }

        :param result: coursier result like the example.
        :return: a simplified view with the top artifact as the roots.
        """
        flat_result = defaultdict(list)

        for artifact in result["dependencies"]:
            flat_result[artifact["coord"]].extend(artifact["dependencies"])

        return flat_result

    @classmethod
    def _map_coord_to_resolved_jars(cls, result, coursier_cache_path, pants_jar_path_base):
        """Map resolved files to each org:name:version.

        Example:
        {
          "conflict_resolution": {},
          "dependencies": [
            {
              "coord": "a",
              "dependencies": ["b", "c"],
              "file": "a.jar"
            },
            {
              "coord": "b",
              "dependencies": [],
              "file": "b.jar"
            },
            {
              "coord": "c",
              "dependencies": [],
              "file": "c.jar"
            },
            {
              "coord": "a:sources",
              "dependencies": ["b", "c"],
              "file": "a-sources.jar"
            },
          ]
        }

        Should return:
        {
          M2Coordinate("a", ...):                             ResolvedJar(classifier='', path/cache_path="a.jar"),
          M2Coordinate("a", ..., classifier="sources"):       ResolvedJar(classifier='sources', path/cache_path="a-sources.jar"),
          M2Coordinate("b", ...):                             ResolvedJar(classifier='', path/cache_path="b.jar"),
          M2Coordinate("c", ...):                             ResolvedJar(classifier='', path/cache_path="c.jar"),
        }

        :param result: coursier json output
        :param coursier_cache_path: coursier cache location
        :param pants_jar_path_base: location under pants workdir to store the hardlink to the coursier cache
        :return: a map from maven coordinate to a resolved jar.
        """

        coord_to_resolved_jars = dict()

        for dep in result["dependencies"]:
            coord = dep["coord"]
            jar_path = dep.get("file", None)
            if not jar_path:
                # NB: Not all coordinates will have associated files.
                #     This is fine. Some coordinates will just have dependencies.
                continue

            if not os.path.exists(jar_path):
                raise CoursierResultNotFound(f"Jar path not found: {jar_path}")

            pants_path = cls._get_path_to_jar(coursier_cache_path, pants_jar_path_base, jar_path)

            if not os.path.exists(pants_path):
                safe_mkdir(os.path.dirname(pants_path))
                safe_hardlink_or_copy(jar_path, pants_path)

            coord = cls.to_m2_coord(coord)
            resolved_jar = ResolvedJar(coord, cache_path=jar_path, pants_path=pants_path)
            coord_to_resolved_jars[coord] = resolved_jar
        return coord_to_resolved_jars

    @classmethod
    def to_m2_coord(cls, coord_str):
        return M2Coordinate.from_string(coord_str)

    @classmethod
    def _get_path_to_jar(cls, coursier_cache_path, pants_jar_path_base, jar_path):
        """Create the path to the jar that will live in .pants.d.

        :param coursier_cache_path: coursier cache location
        :param pants_jar_path_base: location under pants workdir to store the hardlink to the coursier cache
        :param jar_path: path of the jar
        :return:
        """
        if os.path.abspath(coursier_cache_path) not in os.path.abspath(jar_path):
            # Appending the string 'absolute' to the jar_path and joining that is a hack to work around
            # python's os.path.join behavior of throwing away all components that come before an
            # absolute path. See https://docs.python.org/3.3/library/os.path.html#os.path.join
            return os.path.join(pants_jar_path_base, os.path.normpath("absolute/" + jar_path))
        else:
            return os.path.join(
                pants_jar_path_base, "relative", os.path.relpath(jar_path, coursier_cache_path)
            )


class CoursierResolve(CoursierMixin, NailgunTask):
    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (JvmResolveSubsystem,)

    @classmethod
    def product_types(cls):
        return ["compile_classpath", "resolve_sources_signal", "resolve_javadocs_signal"]

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        # Codegen may inject extra resolvable deps, so make sure we have a product dependency
        # on relevant codegen tasks, if any.
        round_manager.optional_data("java")
        round_manager.optional_data("scala")

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("CoursierResolve", 2)]

    def execute(self):
        """Resolves the specified confs for the configured targets and returns an iterator over
        tuples of (conf, jar path)."""

        classpath_products = self.context.products.get_data(
            "compile_classpath",
            init_func=ClasspathProducts.init_func(self.get_options().pants_workdir),
        )
        executor = self.create_java_executor()
        self.resolve(
            self.context.targets(),
            classpath_products,
            sources=self.context.products.is_required_data("resolve_sources_signal"),
            javadoc=self.context.products.is_required_data("resolve_javadocs_signal"),
            executor=executor,
        )

    def check_artifact_cache_for(self, invalidation_check):
        # Coursier resolution is an output dependent on the entire target set, and is not divisible
        # by target. So we can only cache it keyed by the entire target set.
        global_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)
        return [global_vts]


class CoursierResolveFingerprintStrategy(FingerprintStrategy):
    def __init__(self, confs):
        super().__init__()
        self._confs = sorted(confs or [])

    def compute_fingerprint(self, target):
        hash_elements_for_target = []
        if isinstance(target, JarLibrary):
            managed_jar_artifact_set = JarDependencyManagement.global_instance().for_target(target)
            if managed_jar_artifact_set:
                hash_elements_for_target.append(str(managed_jar_artifact_set.id))

            hash_elements_for_target.append(target.payload.fingerprint())
        elif isinstance(target, JvmTarget) and target.payload.excludes:
            hash_elements_for_target.append(target.payload.fingerprint(field_keys=("excludes",)))
        else:
            pass

        if not hash_elements_for_target:
            return None

        hasher = hashlib.sha1()
        hasher.update(target.payload.fingerprint().encode())

        for conf in self._confs:
            hasher.update(conf.encode())

        for element in hash_elements_for_target:
            hasher.update(element.encode())

        # Just in case so we do not collide with ivy cache
        hasher.update(b"coursier")

        return hasher.hexdigest()

    def __hash__(self):
        return hash((type(self), "-".join(self._confs)))

    def __eq__(self, other):
        return type(self) == type(other) and self._confs == other._confs
