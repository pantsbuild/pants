# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
from collections import namedtuple
from textwrap import dedent
from typing import Callable, Dict, List

import pytest

from pants.backend.jvm.tasks.jvm_compile.rsc.rsc_compile import RscCompile
from pants.base.build_environment import get_buildroot
from pants.fs.archive import TGZ, ZIP
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import fast_relpath, safe_mkdir, safe_open, safe_rmtree
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


class Compile(namedtuple("Compile", ["srcfiles", "config", "artifact_count"])):
    pass


class CacheCompileIntegrationTest(BaseCompileIT):
    @classmethod
    def use_pantsd_env_var(cls):
        """TODO(#7320): See the point about watchman."""
        return False

    def run_compile(self, target_spec, config, workdir):
        args = ["compile", target_spec]
        pants_run = self.run_pants_with_workdir(args, workdir, config)
        self.assert_success(pants_run)
        return pants_run

    def create_file(self, path, value):
        with safe_open(path, "w") as f:
            f.write(value)

    def test_transitive_invalid_target_is_dep(self):
        with temporary_dir() as cache_dir, temporary_dir(root_dir=get_buildroot()) as src_dir:

            config = {
                "cache.compile.rsc": {"write_to": [cache_dir], "read_from": [cache_dir]},
                "compile.rsc": {"incremental_caching": True},
                "java": {"strict_deps": False},
            }
            target_dir = os.path.join(src_dir, "org", "pantsbuild", "cachetest")
            a_srcfile = os.path.join(target_dir, "A.java")
            b_srcfile = os.path.join(target_dir, "B.java")
            c_srcfile = os.path.join(target_dir, "C.java")
            buildfile = os.path.join(target_dir, "BUILD")

            self.create_file(
                a_srcfile,
                dedent(
                    """package org.pantsbuild.cachetest;
                    class A {}
                    """
                ),
            )
            self.create_file(
                b_srcfile,
                dedent(
                    """package org.pantsbuild.cachetest;
                    class B {
                      A a;
                    }
                    """
                ),
            )
            self.create_file(
                c_srcfile,
                dedent(
                    """package org.pantsbuild.cachetest;
                    class C {
                      A a;
                    }
                    """
                ),
            )

            self.create_file(
                buildfile,
                dedent(
                    """
                    java_library(name='a',
                                 sources=['A.java']
                    )

                    java_library(name='b',
                                 sources=['B.java'],
                                 dependencies=[':a']
                    )

                    java_library(name='c',
                                 sources=['C.java'],
                                 dependencies=[':b']
                    )
                    """
                ),
            )

            c_spec = os.path.join(os.path.basename(src_dir), "org", "pantsbuild", "cachetest:c")

            with self.temporary_workdir() as workdir:
                self.run_compile(c_spec, config, workdir)
            # clean workdir

            # rm cache entries for a and b
            cache_dir_entries = os.listdir(os.path.join(cache_dir))
            zinc_dir = os.path.join(cache_dir, cache_dir_entries[0])
            c_or_a_cache_dirs = [
                subdir
                for subdir in os.listdir(zinc_dir)
                if subdir.endswith("cachetest.a") or subdir.endswith("cachetest.c")
            ]
            for subdir in c_or_a_cache_dirs:
                safe_rmtree(os.path.join(zinc_dir, subdir))

            # run compile
            with self.temporary_workdir() as workdir:
                self.run_compile(c_spec, config, workdir)

    def test_stale_artifacts_rmd_when_cache_used_with_zinc(self):
        with temporary_dir() as cache_dir, self.temporary_workdir() as workdir, temporary_dir(
            root_dir=get_buildroot()
        ) as src_dir:

            config = {
                "cache.compile.rsc": {"write_to": [cache_dir], "read_from": [cache_dir]},
                "compile.rsc": {"incremental_caching": True},
            }

            srcfile = os.path.join(src_dir, "org", "pantsbuild", "cachetest", "A.java")
            buildfile = os.path.join(src_dir, "org", "pantsbuild", "cachetest", "BUILD")

            self.create_file(
                srcfile,
                dedent(
                    """package org.pantsbuild.cachetest;
                    class A {}
                    class Main {}"""
                ),
            )
            self.create_file(
                buildfile,
                dedent(
                    """java_library(name='cachetest',
                                 sources=['A.java']
                    )"""
                ),
            )

            cachetest_spec = os.path.join(
                os.path.basename(src_dir), "org", "pantsbuild", "cachetest:cachetest"
            )

            # Caches values A.class, Main.class
            self.run_compile(cachetest_spec, config, workdir)

            self.create_file(
                srcfile,
                dedent(
                    """package org.pantsbuild.cachetest;
                    class A {}
                    class NotMain {}"""
                ),
            )
            # Caches values A.class, NotMain.class and leaves them on the filesystem
            self.run_compile(cachetest_spec, config, workdir)

            self.create_file(
                srcfile,
                dedent(
                    """package org.pantsbuild.cachetest;
                    class A {}
                    class Main {}"""
                ),
            )

            # Should cause NotMain.class to be removed
            self.run_compile(cachetest_spec, config, workdir)

            root = os.path.join(workdir, "compile", "rsc")

            task_versions = [p for p in os.listdir(root) if p != "current"]
            self.assertEqual(len(task_versions), 1, "Expected 1 task version.")
            versioned_root = os.path.join(root, task_versions[0])

            per_target_dirs = os.listdir(versioned_root)
            self.assertEqual(len(per_target_dirs), 1, "Expected 1 target.")
            target_workdir_root = os.path.join(versioned_root, per_target_dirs[0])

            target_workdirs = os.listdir(target_workdir_root)
            self.assertEqual(
                len(target_workdirs), 3, "Expected 3 workdirs (current, and two versioned)."
            )
            self.assertIn("current", target_workdirs)

            def classfiles(d):
                cd = os.path.join(
                    target_workdir_root, d, "zinc", "classes", "org", "pantsbuild", "cachetest"
                )
                return sorted(os.listdir(cd))

            # One workdir should contain NotMain, and the other should contain Main.
            self.assertEqual(
                sorted(classfiles(w) for w in target_workdirs if w != "current"),
                sorted([["A.class", "Main.class"], ["A.class", "NotMain.class"]]),
            )

    def test_analysis_portability(self):
        # Tests that analysis can be relocated between workdirs and still result in incremental
        # compile.
        with temporary_dir() as cache_dir, temporary_dir(
            root_dir=get_buildroot()
        ) as src_dir, temporary_dir(root_dir=get_buildroot(), suffix=".pants.d") as workdir:
            config = {
                "cache.compile.rsc": {"write_to": [cache_dir], "read_from": [cache_dir]},
            }

            dep_src_file = os.path.join(src_dir, "org", "pantsbuild", "dep", "A.scala")
            dep_build_file = os.path.join(src_dir, "org", "pantsbuild", "dep", "BUILD")
            con_src_file = os.path.join(src_dir, "org", "pantsbuild", "consumer", "B.scala")
            con_build_file = os.path.join(src_dir, "org", "pantsbuild", "consumer", "BUILD")

            dep_spec = os.path.join(os.path.basename(src_dir), "org", "pantsbuild", "dep")
            con_spec = os.path.join(os.path.basename(src_dir), "org", "pantsbuild", "consumer")

            dep_src = "package org.pantsbuild.dep; class A {}"

            self.create_file(dep_src_file, dep_src)
            self.create_file(dep_build_file, "scala_library()")
            self.create_file(
                con_src_file,
                dedent(
                    """package org.pantsbuild.consumer
                    import org.pantsbuild.dep.A
                    class B { def mkA: A = new A() }"""
                ),
            )
            self.create_file(con_build_file, f"scala_library(dependencies=['{dep_spec}'])")

            rel_workdir = fast_relpath(workdir, get_buildroot())
            rel_src_dir = fast_relpath(src_dir, get_buildroot())
            with self.mock_buildroot(
                dirs_to_copy=[rel_src_dir, rel_workdir]
            ) as buildroot, buildroot.pushd():
                # 1) Compile in one buildroot.
                self.run_compile(
                    con_spec, config, os.path.join(buildroot.new_buildroot, rel_workdir)
                )

            with self.mock_buildroot(
                dirs_to_copy=[rel_src_dir, rel_workdir]
            ) as buildroot, buildroot.pushd():
                # 2) Compile in another buildroot, and check that we hit the cache.
                new_workdir = os.path.join(buildroot.new_buildroot, rel_workdir)
                run_two = self.run_compile(con_spec, config, new_workdir)
                self.assertTrue(
                    re.search("Using cached artifacts for 2 targets.", run_two.stdout_data),
                    run_two.stdout_data,
                )

                # 3) Edit the dependency in a way that should trigger an incremental
                #    compile of the consumer.
                mocked_dep_src_file = os.path.join(
                    buildroot.new_buildroot, fast_relpath(dep_src_file, get_buildroot())
                )
                self.create_file(mocked_dep_src_file, dep_src + "; /* this is a comment */")

                # 4) Compile and confirm that the analysis fetched from the cache in
                #    step 2 causes incrementalism: ie, zinc does not report compiling any files.
                run_three = self.run_compile(con_spec, config, new_workdir)
                self.assertTrue(
                    re.search(r"consumer[\s\S]*Compile success", run_three.stdout_data),
                    run_three.stdout_data,
                )

    def test_incremental_caching(self):
        """Tests that with --no-incremental-caching, we don't write incremental artifacts."""

        srcfile = "A.java"

        def config(incremental_caching):
            return {"compile.rsc": {"incremental_caching": incremental_caching}}

        self._do_test_caching(
            Compile({srcfile: "class A {}"}, config(False), 1),
            Compile({srcfile: "final class A {}"}, config(False), 1),
            Compile({srcfile: "public final class A {}"}, config(True), 2),
        )

    @pytest.mark.skip(reason="flaky: https://github.com/pantsbuild/pants/issues/9312")
    def test_rsc_and_zinc_caching(self):
        """Tests that with rsc-and-zinc, we write both artifacts."""

        srcfile1 = "A.scala"
        srcfile2 = "B.scala"

        def take_only_subdir(curdir, child_name=None):
            children = os.listdir(curdir)
            if child_name:
                self.assertEqual(children, [child_name])
            else:
                self.assertEqual(len(children), 1)
            child = children[0]
            return os.path.join(curdir, child)

        def descend_subdirs(curdir, descendants):
            if not descendants:
                return curdir
            nextdir = take_only_subdir(curdir, descendants[0])
            return descend_subdirs(nextdir, descendants[1:])

        def work(compile, cache_test_subdirs):
            def ensure_classfiles(target_name, classfiles):
                cache_test_subdir = cache_test_subdirs[target_name]
                cache_dir_entries = os.listdir(cache_test_subdir)
                self.assertEqual(len(cache_dir_entries), 1)
                cache_entry = cache_dir_entries[0]

                with self.temporary_workdir() as cache_unzip_dir, self.temporary_workdir() as rsc_dir, self.temporary_workdir() as zinc_dir:

                    cache_path = os.path.join(cache_test_subdir, cache_entry)
                    TGZ.extract(cache_path, cache_unzip_dir)
                    # assert that the unzip dir has the directory structure
                    # ./compile/rsc/{hash}/{x}.{target_name}/{hash2}
                    path = descend_subdirs(cache_unzip_dir, ["compile", "rsc", None, None])
                    self.assertTrue(path.endswith(f".{target_name}"))
                    path = take_only_subdir(path)

                    # TODO: Surprisingly, rsc/m.jar is created even for dependee-less targets.
                    self.assertEqual(sorted(os.listdir(path)), ["rsc", "zinc"])

                    # Check that zinc/z.jar and rsc/m.jar both exist
                    # and that their contents contain the right classfiles
                    zincpath = os.path.join(path, "zinc")
                    zjar = os.path.join(zincpath, "z.jar")
                    self.assertTrue(os.path.exists(zjar))
                    ZIP.extract(zjar, zinc_dir)
                    self.assertEqual(
                        sorted(os.listdir(zinc_dir)), sorted(["compile_classpath", *classfiles])
                    )

                    rscpath = os.path.join(path, "rsc")
                    mjar = os.path.join(rscpath, "m.jar")
                    self.assertTrue(os.path.exists(mjar))
                    ZIP.extract(mjar, rsc_dir)
                    self.assertEqual(sorted(os.listdir(rsc_dir)), sorted(classfiles))

            ensure_classfiles("cachetestA", ["A.class"])
            ensure_classfiles("cachetestB", ["B.class"])

        config = {"compile.rsc": {"workflow": RscCompile.JvmCompileWorkflowType.rsc_and_zinc.value}}
        self._compile_spec(
            [Compile({srcfile1: "class A {}", srcfile2: "class B {}"}, config, 1)],
            [
                "scala_library(name='cachetestA', sources=['A.scala'])",
                "scala_library(name='cachetestB', sources=['B.scala'], dependencies=[':cachetestA'])",
            ],
            ["cachetestA", "cachetestB"],
            "cachetestB",
            work,
        )

    def test_incremental(self):
        """Tests that with --no-incremental and --no-incremental-caching, we always write
        artifacts."""

        srcfile = "A.java"
        config = {"compile.rsc": {"incremental": False, "incremental_caching": False}}

        self._do_test_caching(
            Compile({srcfile: "class A {}"}, config, 1),
            Compile({srcfile: "final class A {}"}, config, 2),
            Compile({srcfile: "public final class A {}"}, config, 3),
        )

    def _compile_spec(
        self,
        compiles: List[Compile],
        target_defs: List[str],
        target_names: List[str],
        target_to_compile: str,
        callback: Callable[
            [Compile, Dict[str, str]], None
        ] = lambda _compile, _cache_test_subdirs: None,
    ) -> None:
        """Compiles a spec within the same workspace under multiple compilation configs, with a
        callback function."""

        with temporary_dir() as cache_dir, self.temporary_workdir() as workdir, temporary_dir(
            root_dir=get_buildroot()
        ) as src_dir:

            def complete_config(config):
                # Clone the input config and add cache settings.
                cache_settings = {"write_to": [cache_dir], "read_from": [cache_dir]}
                return dict(list(config.items()) + [("cache.compile.rsc", cache_settings)])

            buildfile = os.path.join(src_dir, "BUILD")
            spec = os.path.join(src_dir, f":{target_to_compile}")
            artifact_dir = None

            for c in compiles:
                # Clear the src directory and recreate the files.
                safe_mkdir(src_dir, clean=True)
                self.create_file(buildfile, "\n".join(target_defs))
                for name, content in c.srcfiles.items():
                    self.create_file(os.path.join(src_dir, name), content)

                # Compile, and confirm that we have the right count of artifacts.
                self.run_compile(spec, complete_config(c.config), workdir)

                artifact_dir = self.get_cache_subdir(cache_dir)

                cache_test_subdirs = {}
                for t in target_names:
                    cache_test_subdirs[t] = os.path.join(
                        artifact_dir, f"{os.path.basename(src_dir)}.{t}",
                    )

                callback(c, cache_test_subdirs)

    def _do_test_caching(self, *compiles):
        """Tests that the given compiles within the same workspace produce the given artifact
        counts."""

        target_name = "cachetest"

        def work(compile, cache_test_subdirs):
            self.assertEqual(len(cache_test_subdirs), 1)
            cache_test_subdir = cache_test_subdirs[target_name]
            self.assertEqual(compile.artifact_count, len(os.listdir(cache_test_subdir)))

        self._compile_spec(
            compiles,
            [f"java_library(name='{target_name}', sources=['**/*.java', '**/*.scala'])"],
            [target_name],
            target_name,
            work,
        )


class CacheCompileIntegrationWithZjarsTest(CacheCompileIntegrationTest):
    _EXTRA_TASK_ARGS = ["--compile-rsc-use-classpath-jars"]
