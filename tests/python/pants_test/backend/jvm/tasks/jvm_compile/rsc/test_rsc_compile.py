# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

from pants.backend.jvm.subsystems.junit import JUnit
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.scoverage_platform import ScoveragePlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_compile.execution_graph import ExecutionGraph
from pants.backend.jvm.tasks.jvm_compile.rsc.rsc_compile import RscCompile, _create_desandboxify_fn
from pants.java.jar.jar_dependency import JarDependency
from pants.option.ranked_value import Rank, RankedValue
from pants.testutil.jvm.nailgun_task_test_base import NailgunTaskTestBase
from pants.testutil.subsystem.util import init_subsystem
from pants.util.contextutil import temporary_dir


class LightWeightVTS:
    # Simple test double that covers the properties referred to by the _compile_jobs method.

    def __init__(self, target):
        self.target = target

    def update(self):
        pass

    def force_invalidate(self):
        pass


class RscCompileTest(NailgunTaskTestBase):
    DEFAULT_CONF = "default"

    @classmethod
    def task_type(cls):
        return RscCompile

    def test_force_compiler_tags(self):
        self.init_dependencies_for_scala_libraries()

        java_target = self.make_target(
            "java/classpath:java_lib",
            target_type=JavaLibrary,
            sources=["com/example/Foo.java"],
            dependencies=[],
            tags={f"use-compiler:{RscCompile.JvmCompileWorkflowType.rsc_and_zinc.value}"},
        )
        scala_target = self.make_target(
            "scala/classpath:scala_lib",
            target_type=ScalaLibrary,
            sources=["com/example/Foo.scala"],
            dependencies=[],
            tags={"use-compiler:zinc-only"},
        )

        with temporary_dir(root_dir=self.build_root) as tmp_dir:
            invalid_targets = [java_target, scala_target]
            task = self.create_task_with_target_roots(target_roots=[java_target])

            jobs = task._create_compile_jobs(
                compile_contexts=self.create_compile_contexts(
                    [java_target, scala_target], task, tmp_dir
                ),
                invalid_targets=invalid_targets,
                invalid_vts=self.wrap_in_vts(invalid_targets),
                classpath_product=None,
            )

            dependee_graph = self.construct_dependee_graph_str(jobs, task)
            self.assertEqual(
                dedent(
                    """
                    double_check_cache(java/classpath:java_lib) <- {
                      zinc[zinc-java](java/classpath:java_lib)
                    }
                    zinc[zinc-java](java/classpath:java_lib) <- {
                      write_to_cache(java/classpath:java_lib)
                    }
                    write_to_cache(java/classpath:java_lib) <- {}
                    double_check_cache(scala/classpath:scala_lib) <- {
                      zinc[zinc-only](scala/classpath:scala_lib)
                    }
                    zinc[zinc-only](scala/classpath:scala_lib) <- {
                      write_to_cache(scala/classpath:scala_lib)
                    }
                    write_to_cache(scala/classpath:scala_lib) <- {}
                    """
                ).strip(),
                dependee_graph,
            )

    def test_no_dependencies_between_scala_and_java_targets(self):
        self.init_dependencies_for_scala_libraries()

        java_target = self.make_target(
            "java/classpath:java_lib",
            target_type=JavaLibrary,
            sources=["com/example/Foo.java"],
            dependencies=[],
        )
        scala_target = self.make_target(
            "scala/classpath:scala_lib",
            target_type=ScalaLibrary,
            sources=["com/example/Foo.scala"],
            dependencies=[],
            tags={f"use-compiler:{RscCompile.JvmCompileWorkflowType.rsc_and_zinc.value}"},
        )

        with temporary_dir(root_dir=self.build_root) as tmp_dir:
            invalid_targets = [java_target, scala_target]
            task = self.create_task_with_target_roots(target_roots=[java_target])

            jobs = task._create_compile_jobs(
                compile_contexts=self.create_compile_contexts(
                    [java_target, scala_target], task, tmp_dir
                ),
                invalid_targets=invalid_targets,
                invalid_vts=self.wrap_in_vts(invalid_targets),
                classpath_product=None,
            )

            dependee_graph = self.construct_dependee_graph_str(jobs, task)
            self.assertEqual(
                dedent(
                    """
                    double_check_cache(java/classpath:java_lib) <- {
                      zinc[zinc-java](java/classpath:java_lib)
                    }
                    zinc[zinc-java](java/classpath:java_lib) <- {
                      write_to_cache(java/classpath:java_lib)
                    }
                    write_to_cache(java/classpath:java_lib) <- {}
                    double_check_cache(scala/classpath:scala_lib) <- {
                      rsc(scala/classpath:scala_lib),
                      zinc[rsc-and-zinc](scala/classpath:scala_lib)
                    }
                    rsc(scala/classpath:scala_lib) <- {
                      write_to_cache(scala/classpath:scala_lib)
                    }
                    zinc[rsc-and-zinc](scala/classpath:scala_lib) <- {
                      write_to_cache(scala/classpath:scala_lib)
                    }
                    write_to_cache(scala/classpath:scala_lib) <- {}
                    """
                ).strip(),
                dependee_graph,
            )

    def test_default_workflow_of_zinc_only_zincs_scala(self):
        self.init_dependencies_for_scala_libraries()

        scala_target = self.make_target(
            "scala/classpath:scala_lib",
            target_type=ScalaLibrary,
            sources=["com/example/Foo.scala"],
            dependencies=[],
        )

        with temporary_dir(root_dir=self.build_root) as tmp_dir:
            invalid_targets = [scala_target]
            task = self.create_task_with_target_roots(
                target_roots=[scala_target], default_workflow="zinc-only",
            )

            jobs = task._create_compile_jobs(
                compile_contexts=self.create_compile_contexts([scala_target], task, tmp_dir),
                invalid_targets=invalid_targets,
                invalid_vts=self.wrap_in_vts(invalid_targets),
                classpath_product=None,
            )

            dependee_graph = self.construct_dependee_graph_str(jobs, task)
            self.assertEqual(
                dedent(
                    """
                    double_check_cache(scala/classpath:scala_lib) <- {
                      zinc[zinc-only](scala/classpath:scala_lib)
                    }
                    zinc[zinc-only](scala/classpath:scala_lib) <- {
                      write_to_cache(scala/classpath:scala_lib)
                    }
                    write_to_cache(scala/classpath:scala_lib) <- {}
                    """
                ).strip(),
                dependee_graph,
            )

    def test_rsc_dep_for_scala_java_and_test_targets(self):
        self._test_outlining_dep_for_scala_java_and_test_targets(False)

    def test_youtline_dep_for_scala_java_and_test_targets(self):
        self._test_outlining_dep_for_scala_java_and_test_targets(True)

    def _test_outlining_dep_for_scala_java_and_test_targets(self, youtline):
        if youtline:
            workflow = RscCompile.JvmCompileWorkflowType.outline_and_zinc
            key_str = "outline"
        else:
            workflow = RscCompile.JvmCompileWorkflowType.rsc_and_zinc
            key_str = "rsc"

        self.set_options(workflow=RankedValue(value=workflow, rank=Rank.CONFIG,))
        self.init_dependencies_for_scala_libraries()

        scala_dep = self.make_target(
            "scala/classpath:scala_dep", target_type=ScalaLibrary, sources=["com/example/Bar.scala"]
        )
        java_target = self.make_target(
            "java/classpath:java_lib",
            target_type=JavaLibrary,
            sources=["com/example/Foo.java"],
            dependencies=[scala_dep],
            tags={"use-compiler:zinc-only"},
        )
        scala_target = self.make_target(
            "scala/classpath:scala_lib",
            target_type=ScalaLibrary,
            sources=["com/example/Foo.scala"],
            dependencies=[scala_dep],
        )

        test_target = self.make_target(
            "scala/classpath:scala_test",
            target_type=JUnitTests,
            sources=["com/example/Test.scala"],
            dependencies=[scala_target],
            tags={"use-compiler:zinc-only"},
        )

        with temporary_dir(root_dir=self.build_root) as tmp_dir:
            invalid_targets = [java_target, scala_target, scala_dep, test_target]
            task = self.create_task_with_target_roots(
                target_roots=[java_target, scala_target, test_target]
            )

            jobs = task._create_compile_jobs(
                compile_contexts=self.create_compile_contexts(invalid_targets, task, tmp_dir),
                invalid_targets=invalid_targets,
                invalid_vts=self.wrap_in_vts(invalid_targets),
                classpath_product=None,
            )

            dependee_graph = self.construct_dependee_graph_str(jobs, task)

            self.maxDiff = None
            # Double curly braces {{}} because f-string
            self.assertEqual(
                dedent(
                    f"""
                     double_check_cache(java/classpath:java_lib) <- {{
                       zinc[zinc-java](java/classpath:java_lib)
                     }}
                     zinc[zinc-java](java/classpath:java_lib) <- {{
                       write_to_cache(java/classpath:java_lib)
                     }}
                     write_to_cache(java/classpath:java_lib) <- {{}}
                     double_check_cache(scala/classpath:scala_lib) <- {{
                       {key_str}(scala/classpath:scala_lib),
                       zinc[{key_str}-and-zinc](scala/classpath:scala_lib)
                     }}
                     {key_str}(scala/classpath:scala_lib) <- {{
                       write_to_cache(scala/classpath:scala_lib),
                       double_check_cache(scala/classpath:scala_test),
                       zinc[zinc-only](scala/classpath:scala_test)
                     }}
                     zinc[{key_str}-and-zinc](scala/classpath:scala_lib) <- {{
                       write_to_cache(scala/classpath:scala_lib)
                     }}
                     write_to_cache(scala/classpath:scala_lib) <- {{}}
                     double_check_cache(scala/classpath:scala_dep) <- {{
                       {key_str}(scala/classpath:scala_dep),
                       zinc[{key_str}-and-zinc](scala/classpath:scala_dep)
                     }}
                     {key_str}(scala/classpath:scala_dep) <- {{
                       double_check_cache(scala/classpath:scala_lib),
                       {key_str}(scala/classpath:scala_lib),
                       zinc[{key_str}-and-zinc](scala/classpath:scala_lib),
                       write_to_cache(scala/classpath:scala_dep),
                       double_check_cache(scala/classpath:scala_test),
                       zinc[zinc-only](scala/classpath:scala_test)
                     }}
                     zinc[{key_str}-and-zinc](scala/classpath:scala_dep) <- {{
                       double_check_cache(java/classpath:java_lib),
                       zinc[zinc-java](java/classpath:java_lib),
                       write_to_cache(scala/classpath:scala_dep)
                     }}
                     write_to_cache(scala/classpath:scala_dep) <- {{}}
                     double_check_cache(scala/classpath:scala_test) <- {{
                       zinc[zinc-only](scala/classpath:scala_test)
                     }}
                     zinc[zinc-only](scala/classpath:scala_test) <- {{
                       write_to_cache(scala/classpath:scala_test)
                     }}
                     write_to_cache(scala/classpath:scala_test) <- {{}}
                     """
                ).strip(),
                dependee_graph,
            )

    def test_scala_lib_with_java_sources_not_passed_to_rsc(self):
        self.init_dependencies_for_scala_libraries()

        java_target = self.make_target(
            "java/classpath:java_lib",
            target_type=JavaLibrary,
            sources=["com/example/Foo.java"],
            dependencies=[],
        )
        scala_target_direct_java_sources = self.make_target(
            "scala/classpath:scala_with_direct_java_sources",
            target_type=ScalaLibrary,
            sources=["com/example/Foo.scala", "com/example/Bar.java"],
            dependencies=[],
        )
        scala_target_indirect_java_sources = self.make_target(
            "scala/classpath:scala_with_indirect_java_sources",
            target_type=ScalaLibrary,
            java_sources=["java/classpath:java_lib"],
            sources=["com/example/Foo.scala"],
            dependencies=[],
        )

        with temporary_dir(root_dir=self.build_root) as tmp_dir:
            invalid_targets = [
                java_target,
                scala_target_direct_java_sources,
                scala_target_indirect_java_sources,
            ]
            task = self.create_task_with_target_roots(
                target_roots=[scala_target_indirect_java_sources, scala_target_direct_java_sources]
            )

            jobs = task._create_compile_jobs(
                compile_contexts=self.create_compile_contexts(invalid_targets, task, tmp_dir),
                invalid_targets=invalid_targets,
                invalid_vts=[LightWeightVTS(t) for t in invalid_targets],
                classpath_product=None,
            )

            dependee_graph = self.construct_dependee_graph_str(jobs, task)

            self.assertEqual(
                dedent(
                    """
                    double_check_cache(java/classpath:java_lib) <- {
                      zinc[zinc-java](java/classpath:java_lib)
                    }
                    zinc[zinc-java](java/classpath:java_lib) <- {
                      write_to_cache(java/classpath:java_lib)
                    }
                    write_to_cache(java/classpath:java_lib) <- {}
                    double_check_cache(scala/classpath:scala_with_direct_java_sources) <- {
                      zinc[zinc-java](scala/classpath:scala_with_direct_java_sources)
                    }
                    zinc[zinc-java](scala/classpath:scala_with_direct_java_sources) <- {
                      write_to_cache(scala/classpath:scala_with_direct_java_sources)
                    }
                    write_to_cache(scala/classpath:scala_with_direct_java_sources) <- {}
                    double_check_cache(scala/classpath:scala_with_indirect_java_sources) <- {
                      zinc[zinc-java](scala/classpath:scala_with_indirect_java_sources)
                    }
                    zinc[zinc-java](scala/classpath:scala_with_indirect_java_sources) <- {
                      write_to_cache(scala/classpath:scala_with_indirect_java_sources)
                    }
                    write_to_cache(scala/classpath:scala_with_indirect_java_sources) <- {}
                    """
                ).strip(),
                dependee_graph,
            )

    def test_desandbox_fn(self):
        # TODO remove this after https://github.com/scalameta/scalameta/issues/1791 is released
        desandbox = _create_desandboxify_fn([".pants.d/cool/beans.*", ".pants.d/c/r/c/.*"])
        self.assertEqual(desandbox("/some/path/.pants.d/cool/beans"), ".pants.d/cool/beans")
        self.assertEqual(desandbox("/some/path/.pants.d/c/r/c/beans"), ".pants.d/c/r/c/beans")
        self.assertEqual(
            desandbox("/some/path/.pants.d/exec-location/.pants.d/c/r/c/beans"),
            ".pants.d/c/r/c/beans",
        )
        self.assertEqual(desandbox("/some/path/outside/workdir"), "/some/path/outside/workdir")
        # NB ensure that a path outside the workdir that partially matches won't be truncated
        self.assertEqual(
            desandbox("/some/path/outside/workdir.pants.d/cool/beans/etc"),
            "/some/path/outside/workdir.pants.d/cool/beans/etc",
        )
        self.assertEqual(desandbox(None), None)
        # ensure that temp workdirs are discovered relative to the buildroot
        desandbox = _create_desandboxify_fn(
            [".pants.d/tmp.pants.d/cool/beans", ".pants.d/tmp.pants.d/c/r/c"]
        )
        self.assertEqual(
            desandbox("/some/path/.pants.d/tmp.pants.d/cool/beans"),
            ".pants.d/tmp.pants.d/cool/beans",
        )
        self.assertEqual(
            desandbox("/some/path/.pants.d/exec-location/.pants.d/tmp.pants.d/cool/beans"),
            ".pants.d/tmp.pants.d/cool/beans",
        )

    def construct_dependee_graph_str(self, jobs, task):
        exec_graph = ExecutionGraph(jobs, task.get_options().print_exception_stacktrace)
        dependee_graph = exec_graph.format_dependee_graph()
        print(dependee_graph)
        return dependee_graph

    def wrap_in_vts(self, invalid_targets):
        return [LightWeightVTS(t) for t in invalid_targets]

    def init_dependencies_for_scala_libraries(self):
        init_subsystem(
            ScalaPlatform,
            {ScalaPlatform.options_scope: {"version": "custom", "suffix_version": "2.12"}},
        )
        init_subsystem(JUnit,)
        init_subsystem(ScoveragePlatform)
        self.make_target(
            "//:scala-library",
            target_type=JarLibrary,
            jars=[JarDependency(org="com.example", name="scala", rev="0.0.0")],
        )
        self.make_target(
            "//:junit-library",
            target_type=JarLibrary,
            jars=[JarDependency(org="com.example", name="scala", rev="0.0.0")],
        )

    def create_task_with_target_roots(self, target_roots, default_workflow=None):
        if default_workflow:
            self.set_options(workflow=RscCompile.JvmCompileWorkflowType(default_workflow))
        context = self.context(target_roots=target_roots)
        self.init_products(context)
        task = self.create_task(context)
        # tried for options, but couldn't get it to reconfig
        task._size_estimator = lambda srcs: 0
        return task

    def init_products(self, context):
        context.products.get_data(
            "compile_classpath", ClasspathProducts.init_func(self.pants_workdir)
        )
        context.products.get_data(
            "runtime_classpath", ClasspathProducts.init_func(self.pants_workdir)
        )

    def create_compile_contexts(self, invalid_targets, task, tmp_dir):
        return {
            target: task.create_compile_context(target, os.path.join(tmp_dir, target.id))
            for target in invalid_targets
        }
