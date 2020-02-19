# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib

from pants.backend.jvm.subsystems.java import Java
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.javac_plugin import JavacPlugin
from pants.backend.jvm.targets.scalac_plugin import ScalacPlugin
from pants.base.fingerprint_strategy import FingerprintStrategy
from pants.base.hash_utils import stable_json_sha1
from pants.build_graph.dependency_context import DependencyContext as DependencyContextBase
from pants.build_graph.resources import Resources
from pants.build_graph.target_scopes import Scopes
from pants.subsystem.subsystem import Subsystem


class SyntheticTargetNotFound(Exception):
    """Exports were resolved for a thrift target which hasn't had a synthetic target generated
    yet."""


class DependencyContext(Subsystem, DependencyContextBase):
    """Implements calculating `exports` and exception (compiler-plugin) aware dependencies.

    This is a subsystem because in future the compiler plugin types should be injected via subsystem
    or option dependencies rather than declared statically.
    """

    options_scope = "jvm-dependency-context"

    types_with_closure = (AnnotationProcessor, JavacPlugin, ScalacPlugin)
    target_closure_kwargs = dict(
        include_scopes=Scopes.JVM_COMPILE_SCOPES, respect_intransitive=True
    )

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (Java, ScalaPlatform)

    def all_dependencies(self, target):
        """All transitive dependencies of the context's target."""
        for dep in target.closure(bfs=True, **self.target_closure_kwargs):
            yield dep

    def create_fingerprint_strategy(self, classpath_products):
        return ResolvedJarAwareFingerprintStrategy(classpath_products, self)

    def defaulted_property(self, target, option_name):
        """Computes a language property setting for the given JvmTarget.

        :param selector A function that takes a target or platform and returns the boolean value of the
                        property for that target or platform, or None if that target or platform does
                        not directly define the property.

        If the target does not override the language property, returns true iff the property
        is true for any of the matched languages for the target.
        """
        if target.has_sources(".java"):
            matching_subsystem = Java.global_instance()
        elif target.has_sources(".scala"):
            matching_subsystem = ScalaPlatform.global_instance()
        else:
            return getattr(target, option_name)

        return matching_subsystem.get_scalar_mirrored_target_option(option_name, target)

    def dependencies_respecting_strict_deps(self, target):
        if self.defaulted_property(target, "strict_deps"):
            dependencies = target.strict_dependencies(self)
        else:
            dependencies = self.all_dependencies(target)
        return dependencies


class ResolvedJarAwareFingerprintStrategy(FingerprintStrategy):
    """Task fingerprint strategy that also includes the resolved coordinates of dependent jars."""

    def __init__(self, classpath_products, dep_context):
        super().__init__()
        self._classpath_products = classpath_products
        self._dep_context = dep_context

    def compute_fingerprint(self, target):
        if isinstance(target, Resources):
            # Just do nothing, this kind of dependency shouldn't affect result's hash.
            return None

        hasher = hashlib.sha1()
        hasher.update(target.payload.fingerprint().encode())
        # Adding tags into cache key because it may decide which workflow applies to the target.
        hasher.update(stable_json_sha1(target.tags).encode())
        if isinstance(target, JarLibrary):
            # NB: Collects only the jars for the current jar_library, and hashes them to ensure that both
            # the resolved coordinates, and the requested coordinates are used. This ensures that if a
            # source file depends on a library with source compatible but binary incompatible signature
            # changes between versions, that you won't get runtime errors due to using an artifact built
            # against a binary incompatible version resolved for a previous compile.
            classpath_entries = self._classpath_products.get_artifact_classpath_entries_for_targets(
                [target]
            )
            for _, entry in classpath_entries:
                hasher.update(str(entry.coordinate).encode())
        return hasher.hexdigest()

    def direct(self, target):
        return self._dep_context.defaulted_property(target, "strict_deps")

    def dependencies(self, target):
        if self.direct(target):
            return target.strict_dependencies(self._dep_context)
        return super().dependencies(target)

    def __hash__(self):
        # NB: FingerprintStrategy requires a useful override of eq/hash.
        return hash(type(self))

    def __eq__(self, other):
        # NB: See __hash__.
        return type(self) == type(other)
