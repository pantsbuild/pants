# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.subsystems.jvm import JVM
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.runtime_platform_mixin import RuntimePlatformMixin
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.build_graph.build_graph import BuildGraph
from pants.build_graph.target_scopes import Scopes
from pants.java.distribution.distribution import DistributionLocator
from pants.task.task import Task


class JvmTask(Task):
    """Base class for tasks that whose explicit user-facing purpose is to run code in a JVM.

    Examples are run.jvm, test.junit, repl.scala.  These tasks (and end users) can configure
    the JVM options, args etc. via the JVM subsystem scoped to the task.

    Note that this is distinct from tasks that happen to run code in a JVM as an implementation
    detail, such as compile.java, checkstyle, etc.  Hypothetically at least, you could imagine
    a Java compiler written in a non-JVM language, and then compile.java might not need to
    run JVM code at all.  In practice that is highly unlikely, but the distinction is still
    important.  Those JVM-tool-using tasks mix in `pants.backend.jvm.tasks.JvmToolTaskMixin`.
    """

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (
            JVM.scoped(cls),
            DistributionLocator,
            JvmPlatform,
        )

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--confs",
            type=list,
            default=["default"],
            help="Use only these Ivy configurations of external deps.",
        )

    @classmethod
    def prepare(cls, options, round_manager):
        round_manager.require_data("runtime_classpath")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.jvm = JVM.scoped_instance(self)
        self.jvm_options = self.jvm.get_jvm_options()
        self.args = self.jvm.get_program_args()
        self.confs = self.get_options().confs
        self.synthetic_classpath = self.jvm.get_options().synthetic_classpath

    def classpath(
        self,
        targets,
        classpath_prefix=None,
        classpath_product=None,
        exclude_scopes=None,
        include_scopes=None,
    ):
        """Builds a transitive classpath for the given targets.

        Optionally includes a classpath prefix or building from a non-default classpath product.

        :param targets: the targets for which to build the transitive classpath.
        :param classpath_prefix: optional additional entries to prepend to the classpath.
        :param classpath_product: an optional ClasspathProduct from which to build the classpath. if not
        specified, the runtime_classpath will be used.
        :param :class:`pants.build_graph.target_scopes.Scope` exclude_scopes: Exclude targets which
          have at least one of these scopes on the classpath.
        :param :class:`pants.build_graph.target_scopes.Scope` include_scopes: Only include targets which
          have at least one of these scopes on the classpath. Defaults to Scopes.JVM_RUNTIME_SCOPES.
        :return: a list of classpath strings.
        """
        include_scopes = Scopes.JVM_RUNTIME_SCOPES if include_scopes is None else include_scopes
        classpath_product = classpath_product or self.context.products.get_data("runtime_classpath")
        closure = BuildGraph.closure(
            targets,
            bfs=True,
            include_scopes=include_scopes,
            exclude_scopes=exclude_scopes,
            respect_intransitive=True,
        )

        classpath_for_targets = ClasspathUtil.classpath(closure, classpath_product, self.confs)
        classpath = list(classpath_prefix or ())
        classpath.extend(classpath_for_targets)
        return classpath

    def preferred_jvm_distribution_for_targets(self, targets, jdk=False, strict=False):
        """Find the preferred jvm distribution for running code from the given targets."""
        return self.preferred_jvm_distribution(
            self.runtime_platforms_for_targets(targets), jdk=jdk, strict=strict
        )

    def runtime_platforms_for_targets(self, targets):
        target_platforms = [
            self._runtime_platform_for_target(target)
            for target in targets
            if isinstance(target, JvmTarget)
        ]
        if not target_platforms:
            return [JvmPlatform.default_runtime_platform]
        else:
            return target_platforms

    def _runtime_platform_for_target(self, target):
        if isinstance(target, RuntimePlatformMixin):
            return target.runtime_platform
        else:
            return target.platform

    def preferred_jvm_distribution(self, platforms, jdk=False, strict=False):
        return JvmPlatform.preferred_jvm_distribution(platforms, jdk=jdk, strict=strict)
