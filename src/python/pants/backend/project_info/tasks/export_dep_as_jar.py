# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import zipfile
from collections import defaultdict
from typing import Dict, List, Tuple

from pants.backend.jvm.subsystems.dependency_context import DependencyContext
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.runtime_platform_mixin import RuntimePlatformMixin
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import ZincCompile
from pants.backend.project_info.tasks.export import SourceRootTypes
from pants.backend.project_info.tasks.export_version import DEFAULT_EXPORT_VERSION
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.java.distribution.distribution import DistributionLocator
from pants.java.jar.jar_dependency_utils import M2Coordinate
from pants.task.console_task import ConsoleTask
from pants.util.contextutil import temporary_file
from pants.util.memo import memoized_property
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


class ExportDepAsJar(ConsoleTask):
    """[Experimental] Create project info for IntelliJ with dependencies treated as jars.

    This is an experimental task that mimics export but uses the jars for
    jvm dependencies instead of sources.

    This goal affects the contents of the runtime_classpath, and should not be
    combined with any other goals on the command line.
    """

    _register_console_transitivity_option = False

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (DependencyContext,)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--formatted",
            type=bool,
            implicit_value=False,
            help="Causes output to be a single line of JSON.",
        )
        register(
            "--sources",
            type=bool,
            help="Causes the sources of dependencies to be zipped and included in the project.",
        )
        register(
            "--libraries-sources",
            type=bool,
            help="Causes 3rdparty libraries with sources to be output.",
        )
        register(
            "--libraries-javadocs",
            type=bool,
            help="Causes 3rdparty libraries with javadocs to be output.",
        )
        register(
            "--respect-strict-deps",
            type=bool,
            default=True,
            help="If true, strict deps are respected like the JVM compile task; otherwise it is "
            "ignored, and this can be useful as a workaround or for debugging purposes.",
        )

    @property
    def act_transitively(self):
        return True

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data("zinc_args")
        round_manager.require_data("runtime_classpath")
        round_manager.require_data("jvm_modulizable_targets")
        if options.libraries_sources:
            round_manager.require_data("resolve_sources_signal")
        if options.libraries_javadocs:
            round_manager.require_data("resolve_javadocs_signal")

    @property
    def _output_folder(self):
        return self.options_scope.replace(".", os.sep)

    @staticmethod
    def _source_roots_for_target(target):
        """
        :type target:pants.build_graph.target.Target
        """

        def root_package_prefix(source_file):
            source = os.path.dirname(source_file)
            return (
                os.path.join(get_buildroot(), target.target_base, source),
                source.replace(os.sep, "."),
            )

        return {root_package_prefix(source) for source in target.sources_relative_to_source_root()}

    @memoized_property
    def target_aliases_map(self):
        registered_aliases = self.context.build_configuration.registered_aliases()
        mapping = {}
        for alias, target_types in registered_aliases.target_types_by_alias.items():
            # If a target class is registered under multiple aliases returns the last one.
            for target_type in target_types:
                mapping[target_type] = alias
        return mapping

    def _get_pants_target_alias(self, pants_target_type):
        """Returns the pants target alias for the given target."""
        if pants_target_type in self.target_aliases_map:
            return self.target_aliases_map.get(pants_target_type)
        else:
            return "{}.{}".format(pants_target_type.__module__, pants_target_type.__name__)

    @staticmethod
    def _jar_id(jar):
        """Create a string identifier for the IvyModuleRef key.

        :param IvyModuleRef jar: key for a resolved jar
        :returns: String representing the key as a maven coordinate
        """
        if jar.rev:
            return "{0}:{1}:{2}".format(jar.org, jar.name, jar.rev)
        else:
            return "{0}:{1}".format(jar.org, jar.name)

    @staticmethod
    def _exclude_id(jar):
        """Create a string identifier for the Exclude key.

        :param Exclude jar: key for an excluded jar
        :returns: String representing the key as a maven coordinate
        """
        return "{0}:{1}".format(jar.org, jar.name) if jar.name else jar.org

    @staticmethod
    def _get_target_type(tgt, resource_target_map, runtime_classpath):
        def is_test(t):
            return isinstance(t, JUnitTests)

        if is_test(tgt):
            return SourceRootTypes.TEST
        else:
            if (
                isinstance(tgt, Resources)
                and tgt in resource_target_map
                and is_test(resource_target_map[tgt])
            ):
                return SourceRootTypes.TEST_RESOURCE
            elif isinstance(tgt, Resources):
                return SourceRootTypes.RESOURCE
            elif not isinstance(tgt, JvmTarget) and runtime_classpath.get_for_target(tgt):
                # It's not a resource, but it also isn't Jvm source code, but it has a entry on the classpath
                # so the classpath entry should be added to
                return SourceRootTypes.RESOURCE_GENERATED
            else:
                return SourceRootTypes.SOURCE

    def _resolve_jars_info(self, targets, classpath_products):
        """Consults ivy_jar_products to export the external libraries.

        :return: mapping of jar_id -> { 'default'     : <jar_file>,
                                        'sources'     : <jar_file>,
                                        'javadoc'     : <jar_file>,
                                        <other_confs> : <jar_file>,
                                      }
        """
        mapping = defaultdict(dict)
        jar_products = classpath_products.get_artifact_classpath_entries_for_targets(
            targets, respect_excludes=False
        )
        for conf, jar_entry in jar_products:
            conf = jar_entry.coordinate.classifier or "default"
            mapping[self._jar_id(jar_entry.coordinate)][conf] = jar_entry.cache_path
        return mapping

    @staticmethod
    def _zip_sources(target, location, suffix=".jar"):
        with temporary_file(root_dir=location, cleanup=False, suffix=suffix) as f:
            with zipfile.ZipFile(f, "a") as zip_file:
                for src_from_source_root, src_from_build_root in zip(
                    target.sources_relative_to_source_root(), target.sources_relative_to_buildroot()
                ):
                    zip_file.write(
                        os.path.join(get_buildroot(), src_from_build_root), src_from_source_root
                    )
        return f

    @staticmethod
    def _extract_arguments_with_prefix_from_zinc_args(
        args: List[str], prefix: str
    ) -> Tuple[str, ...]:
        return tuple([option[len(prefix) :] for option in args if option.startswith(prefix)])

    def _compute_transitive_source_dependencies(
        self,
        target: Target,
        info_entry: Tuple[str, ...],
        modulizable_target_set: FrozenOrderedSet[Target],
    ) -> Tuple[str, ...]:
        if self._is_strict_deps(target):
            return info_entry
        else:
            transitive_targets = OrderedSet(info_entry)
            self.context.build_graph.walk_transitive_dependency_graph(
                addresses=[target.address],
                predicate=lambda d: d in modulizable_target_set,
                work=lambda d: transitive_targets.add(d.address.spec),
            )
            return tuple(transitive_targets)

    def _process_target(
        self,
        current_target: Target,
        modulizable_target_set: FrozenOrderedSet[Target],
        resource_target_map,
        runtime_classpath,
        zinc_args_for_target,
        flat_non_modulizable_deps_for_modulizable_targets,
    ):
        """
        :type current_target:pants.build_graph.target.Target
        """
        info = {
            # this means 'dependencies'
            "targets": [],
            "source_dependencies_in_classpath": [],
            "libraries": [],
            "roots": [],
            "id": current_target.id,
            "target_type": ExportDepAsJar._get_target_type(
                current_target, resource_target_map, runtime_classpath
            ),
            "is_synthetic": current_target.is_synthetic,
            "pants_target_type": self._get_pants_target_alias(type(current_target)),
            "is_target_root": current_target in modulizable_target_set,
            "transitive": current_target.transitive,
            "scope": str(current_target.scope),
            "scalac_args": ExportDepAsJar._extract_arguments_with_prefix_from_zinc_args(
                zinc_args_for_target, "-S"
            ),
            "javac_args": ExportDepAsJar._extract_arguments_with_prefix_from_zinc_args(
                zinc_args_for_target, "-C"
            ),
            "extra_jvm_options": current_target.payload.get_field_value("extra_jvm_options", []),
        }

        def iter_transitive_jars(jar_lib):
            """
            :type jar_lib: :class:`pants.backend.jvm.targets.jar_library.JarLibrary`
            :rtype: :class:`collections.Iterator` of
                    :class:`pants.java.jar.M2Coordinate`
            """
            if runtime_classpath:
                jar_products = runtime_classpath.get_artifact_classpath_entries_for_targets(
                    (jar_lib,)
                )
                for _, jar_entry in jar_products:
                    coordinate = jar_entry.coordinate
                    # We drop classifier and type_ since those fields are represented in the global
                    # libraries dict and here we just want the key into that dict (see `_jar_id`).
                    yield M2Coordinate(org=coordinate.org, name=coordinate.name, rev=coordinate.rev)

        def _full_library_set_for_target(target):
            """Get the full library set for a target, including jar dependencies and jars of the
            library itself."""
            libraries = set([])
            if isinstance(target, JarLibrary):
                jars = set([])
                for jar in target.jar_dependencies:
                    jars.add(M2Coordinate(jar.org, jar.name, jar.rev))
                # Add all the jars pulled in by this jar_library
                jars.update(iter_transitive_jars(target))
                libraries = [self._jar_id(jar) for jar in jars]
            else:
                libraries.add(target.id)
            return libraries

        if not current_target.is_synthetic:
            info["globs"] = current_target.globs_relative_to_buildroot()

        libraries_for_target = set(
            [self._jar_id(jar) for jar in iter_transitive_jars(current_target)]
        )
        for dep in sorted(flat_non_modulizable_deps_for_modulizable_targets[current_target]):
            libraries_for_target.update(_full_library_set_for_target(dep))
        info["libraries"].extend(libraries_for_target)

        info["roots"] = [
            {
                "source_root": os.path.realpath(source_root_package_prefix[0]),
                "package_prefix": source_root_package_prefix[1],
            }
            for source_root_package_prefix in self._source_roots_for_target(current_target)
        ]

        for dep in current_target.dependencies:
            if dep in modulizable_target_set:
                info["targets"].append(dep.address.spec)

        if isinstance(current_target, ScalaLibrary):
            for dep in current_target.java_sources:
                info["targets"].append(dep.address.spec)

        if isinstance(current_target, JvmTarget):
            info["excludes"] = [self._exclude_id(exclude) for exclude in current_target.excludes]
            info["platform"] = current_target.platform.name
            if isinstance(current_target, RuntimePlatformMixin):
                info["runtime_platform"] = current_target.runtime_platform.name

        info["source_dependencies_in_classpath"] = self._compute_transitive_source_dependencies(
            current_target, info["targets"], modulizable_target_set
        )

        return info

    def initialize_graph_info(self):
        scala_platform = ScalaPlatform.global_instance()
        scala_platform_map = {
            "scala_version": scala_platform.version,
            "compiler_classpath": [
                cp_entry.path
                for cp_entry in scala_platform.compiler_classpath_entries(self.context.products)
            ],
        }

        jvm_platforms_map = {
            "default_platform": JvmPlatform.global_instance().default_platform.name,
            "platforms": {
                str(platform_name): {
                    "target_level": str(platform.target_level),
                    "source_level": str(platform.source_level),
                    "args": platform.args,
                }
                for platform_name, platform in JvmPlatform.global_instance().platforms_by_name.items()
            },
        }

        graph_info = {
            "version": DEFAULT_EXPORT_VERSION,
            "targets": {},
            "jvm_platforms": jvm_platforms_map,
            "scala_platform": scala_platform_map,
            # `jvm_distributions` are static distribution settings from config,
            # `preferred_jvm_distributions` are distributions that pants actually uses for the
            # given platform setting.
            "preferred_jvm_distributions": {},
        }

        for platform_name, platform in JvmPlatform.global_instance().platforms_by_name.items():
            preferred_distributions = {}
            for strict, strict_key in [(True, "strict"), (False, "non_strict")]:
                try:
                    dist = JvmPlatform.preferred_jvm_distribution([platform], strict=strict)
                    preferred_distributions[strict_key] = dist.home
                except DistributionLocator.Error:
                    pass

            if preferred_distributions:
                graph_info["preferred_jvm_distributions"][platform_name] = preferred_distributions

        return graph_info

    def _get_all_targets(self, targets):
        additional_java_targets = []
        for t in targets:
            if isinstance(t, ScalaLibrary):
                additional_java_targets.extend(t.java_sources)
        targets.extend(additional_java_targets)
        return set(targets)

    def _get_targets_to_make_into_modules(self, resource_target_map, runtime_classpath):
        jvm_modulizable_targets = self.context.products.get_data("jvm_modulizable_targets")
        non_generated_resource_jvm_modulizable_targets = [
            t
            for t in jvm_modulizable_targets
            if self._get_target_type(t, resource_target_map, runtime_classpath)
            is not SourceRootTypes.RESOURCE_GENERATED
        ]
        return non_generated_resource_jvm_modulizable_targets

    def _make_libraries_entry(self, target, resource_target_map, runtime_classpath):
        # Using resolved path in preparation for VCFS.
        resource_jar_root = os.path.realpath(self.versioned_workdir)
        library_entry = {}
        target_type = ExportDepAsJar._get_target_type(
            target, resource_target_map, runtime_classpath
        )
        if target_type == SourceRootTypes.RESOURCE or target_type == SourceRootTypes.TEST_RESOURCE:
            # yic assumed that the cost to fingerprint the target may not be that lower than
            # just zipping up the resources anyway.
            jarred_resources = ExportDepAsJar._zip_sources(target, resource_jar_root)
            library_entry["default"] = jarred_resources.name
        elif target_type == SourceRootTypes.RESOURCE_GENERATED:
            library_entry.update(
                [
                    (conf, os.path.realpath(path_entry))
                    for conf, path_entry in runtime_classpath.get_for_target(target)
                ]
            )
        else:
            jar_products = runtime_classpath.get_for_target(target)
            for conf, jar_entry in jar_products:
                # TODO(yic): check --compile-rsc-use-classpath-jars is enabled.
                # If not, zip up the classes/ dir here.
                if "z.jar" in jar_entry:
                    library_entry[conf] = jar_entry
            if self.get_options().sources:
                # NB: We create the jar in the same place as we create the resources
                # (as opposed to where we store the z.jar), because the path to the z.jar depends
                # on tasks outside of this one.
                # In addition to that, we may not want to depend on z.jar existing to export source jars.
                jarred_sources = ExportDepAsJar._zip_sources(
                    target, resource_jar_root, suffix="-sources.jar"
                )
                library_entry["sources"] = jarred_sources.name
        return library_entry

    def _is_strict_deps(self, target: Target) -> bool:
        if not self.get_options().respect_strict_deps:
            return False

        return isinstance(
            target, JvmTarget
        ) and DependencyContext.global_instance().defaulted_property(target, "strict_deps")

    def _flat_non_modulizable_deps_for_modulizable_targets(
        self, modulizable_targets: FrozenOrderedSet[Target]
    ) -> Dict[Target, FrozenOrderedSet[Target]]:
        """Collect flat dependencies for targets that will end up in libraries. When visiting a
        target, we don't expand the dependencies that are modulizable targets, since we need to
        reflect those relationships in a separate way later on.

        E.g. if A -> B -> C -> D and A -> E and B -> F, if modulizable_targets = {A, B}, the resulting map will be:
         {
            A -> {E},
            B -> {C, F, D},

            // Some other entries for intermediate dependencies
            C -> {D},
            E -> {},
            F -> {},
         }
        Therefore, when computing the library entries for A, we need to walk the (transitive) modulizable dependency graph,
        and accumulate the entries in the map.

        This function takes strict_deps into account when generating the graph.
        """
        flat_deps: Dict[Target, FrozenOrderedSet[Target]] = {}

        def create_entry_for_target(target: Target) -> None:
            target_key = target
            if self._is_strict_deps(target):
                dependencies = target.strict_dependencies(DependencyContext.global_instance())
            else:
                dependencies = target.dependencies
            non_modulizable_deps = [dep for dep in dependencies if dep not in modulizable_targets]
            entry: OrderedSet[Target] = OrderedSet()
            for dep in non_modulizable_deps:
                entry.update(flat_deps.get(dep, set()).union({dep}))
            flat_deps[target_key] = FrozenOrderedSet(entry)

        targets_with_strict_deps = [t for t in modulizable_targets if self._is_strict_deps(t)]
        for t in targets_with_strict_deps:
            flat_deps[t] = FrozenOrderedSet(
                t.strict_dependencies(DependencyContext.global_instance())
            )

        self.context.build_graph.walk_transitive_dependency_graph(
            addresses=[t.address for t in modulizable_targets if not self._is_strict_deps(t)],
            # Work is to populate the entry of the map by merging the entries of all of the deps.
            work=create_entry_for_target,
            # We pre-populate the dict according to several principles (e.g. strict_deps),
            # so a target being there means that there is no need to expand.
            predicate=lambda target: target not in flat_deps.keys(),
            # We want children to populate their entries in the map before the parents,
            # so that we are guaranteed to have entries for all dependencies before
            # computing a target's entry.
            postorder=True,
        )
        return flat_deps

    def generate_targets_map(self, targets, runtime_classpath, zinc_args_for_all_targets):
        """Generates a dictionary containing all pertinent information about the target graph.

        The return dictionary is suitable for serialization by json.dumps.
        :param all_targets: The list of targets to generate the map for.
        :param runtime_classpath: ClasspathProducts containing entries for all the resolved and compiled
          dependencies.
        :param zinc_args_for_all_targets: Map from zinc compiled targets to the args used to compile them.
        """
        all_targets = self._get_all_targets(targets)
        libraries_map = self._resolve_jars_info(all_targets, runtime_classpath)

        targets_map = {}
        resource_target_map = {}

        for t in all_targets:
            for dep in t.dependencies:
                if isinstance(dep, Resources):
                    resource_target_map[dep] = t

        modulizable_targets = self._get_targets_to_make_into_modules(
            resource_target_map, runtime_classpath
        )
        non_modulizable_targets = all_targets.difference(modulizable_targets)

        for t in non_modulizable_targets:
            libraries_map[t.id] = self._make_libraries_entry(
                t, resource_target_map, runtime_classpath
            )

        flat_non_modulizable_deps_for_modulizable_targets: Dict[
            Target, FrozenOrderedSet[Target]
        ] = self._flat_non_modulizable_deps_for_modulizable_targets(modulizable_targets)

        for target in modulizable_targets:
            zinc_args_for_target = zinc_args_for_all_targets.get(target)
            if zinc_args_for_target is None:
                if not ZincCompile.select(target):
                    # Targets that weren't selected by ZincCompile also wont have zinc args.
                    zinc_args_for_target = []
                else:
                    raise TaskError(
                        f"There was an error exporting target {target} - There were no zinc arguments registered for it"
                    )
            info = self._process_target(
                target,
                modulizable_targets,
                resource_target_map,
                runtime_classpath,
                zinc_args_for_target,
                flat_non_modulizable_deps_for_modulizable_targets,
            )
            targets_map[target.address.spec] = info

        graph_info = self.initialize_graph_info()
        graph_info["targets"] = targets_map
        graph_info["libraries"] = libraries_map

        return graph_info

    def console_output(self, targets):
        zinc_args_for_all_targets = self.context.products.get_data("zinc_args")

        if zinc_args_for_all_targets is None:
            raise TaskError(
                "There was an error compiling the targets - There there are no zing argument entries"
            )

        runtime_classpath = self.context.products.get_data("runtime_classpath")
        if runtime_classpath is None:
            raise TaskError(
                "There was an error compiling the targets - There is no runtime_classpath classpath"
            )
        graph_info = self.generate_targets_map(
            targets,
            runtime_classpath=runtime_classpath,
            zinc_args_for_all_targets=zinc_args_for_all_targets,
        )

        if self.get_options().formatted:
            return json.dumps(graph_info, indent=4, separators=(",", ": ")).splitlines()
        else:
            return [json.dumps(graph_info)]
