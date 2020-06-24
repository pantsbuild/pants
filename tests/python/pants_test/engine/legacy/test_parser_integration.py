# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
from contextlib import contextmanager
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import fast_relpath, safe_file_dump
from pants_test.pantsd.pantsd_integration_test_base import PantsDaemonIntegrationTestBase


class LoadStatementsIntegrationTests(PantsDaemonIntegrationTestBase):
    @contextmanager
    def _mock_broken_project_dir(self, build_file_content):
        with temporary_dir(root_dir=get_buildroot()) as tmpdir:
            bad_build_file = os.path.join(tmpdir, "BUILD")
            safe_file_dump(bad_build_file, build_file_content)
            yield tmpdir

    def test_files_with_load_statements_parse(self):
        pants_run = self.do_command(
            "list",
            "examples/src/scala/org/pantsbuild/example/build_file_macros:build_file_macros",
            success=True,
        )
        assert {
            "examples/src/scala/org/pantsbuild/example/build_file_macros:build_file_macros"
        } == set(pants_run.stdout_data.splitlines())

    def test_macro_definitions_have_access_to_registered_concepts(self):
        # We check that we can use pants concepts in loaded macros.
        # We run `export` instead of list to force the parsing and understanding of the custom artifact.
        pants_run = self.do_command(
            "export",
            "examples/src/scala/org/pantsbuild/example/build_file_macros:provides_custom_artifact",
            success=True,
        )
        assert (
            "examples/src/scala/org/pantsbuild/example/build_file_macros:provides_custom_artifact"
            in pants_run.stdout_data
        )

    def test_only_load_specified_symbols(self):
        fail_to_load_symbols_build_file = dedent(
            """
            # source_exe_scala should come from this file, but we don't expose it.
            load("examples/src/scala/org/pantsbuild/example/build_file_macros/BUILD_MACROS_2")
            
            jvm_binary(
              main="org.pantsbuild.example.build_file_macros.Exe",
              sources=source_exe_scala(),
            )
            """
        )

        with self._mock_broken_project_dir(fail_to_load_symbols_build_file) as tmpdir:
            pants_run = self.do_command("list", f"{tmpdir}:", success=False,)
            assert "name 'source_exe_scala' is not defined" in pants_run.stderr_data

    def test_cannot_load_symbol_twice(self):
        load_symbol_from_multiple_files = dedent(
            """
            # We try to load the same symbol from two different files.
            load("examples/src/scala/org/pantsbuild/example/build_file_macros/BUILD_MACROS_2", "source_exe_scala")
            load("examples/src/scala/org/pantsbuild/example/build_file_macros/BUILD_MACROS_3", "source_exe_scala")

            jvm_binary(
              main="org.pantsbuild.example.build_file_macros.Exe",
              sources=source_exe_scala(),
            )
            """
        )

        with self._mock_broken_project_dir(load_symbol_from_multiple_files) as tmpdir:
            pants_run = self.do_command("list", f"{tmpdir}:", success=False,)
            assert "Which has already been loaded from another file." in pants_run.stderr_data

    def test_cannot_load_non_existing_symbol(self):
        load_non_existing_symbol = dedent(
            """
            # We try to load the same symbol from two different files.
            load("examples/src/scala/org/pantsbuild/example/build_file_macros/BUILD_MACROS", "bad_symbol")

            jvm_binary(
              main="org.pantsbuild.example.build_file_macros.Exe",
              sources=bad_symbol(),
            )
            """
        )

        with self._mock_broken_project_dir(load_non_existing_symbol) as tmpdir:
            pants_run = self.do_command("list", f"{tmpdir}:", success=False,)
            assert "Symbol is not exported by loaded file." in pants_run.stderr_data

    def test_cannot_load_non_existing_file(self):
        load_non_existing_symbol = dedent(
            """
            # We try to load the same symbol from two different files.
            load("non/existing/file", "mock_sources")

            jvm_binary(
              main="org.pantsbuild.example.build_file_macros.Exe",
              source=mock_sources(),
            )
            """
        )

        with self._mock_broken_project_dir(load_non_existing_symbol) as tmpdir:
            pants_run = self.do_command("list", f"{tmpdir}:", success=False,)
            assert 'Tried to load non existing file: "non/existing/file"' in pants_run.stderr_data

    def test_macro_files_ignore_loads_if_loaded_symbols_are_registered(self):
        ignore_registered_symbols_load_build_file = dedent(
            """
            # We try to load a macro file that itself has load() statements,
            # and all statements load symbols registered with pants.
            load("examples/src/scala/org/pantsbuild/example/build_file_macros/MACRO_THAT_LOADS_REGISTERED_MACROS")

            target(name="dummy")
            """
        )

        with self._mock_broken_project_dir(ignore_registered_symbols_load_build_file) as tmpdir:
            pants_run = self.do_command("list", f"{tmpdir}:", success=True,)
            assert ":dummy" in pants_run.stdout_data

    def test_macro_files_error_if_trying_to_load_non_registered_symbols(self):
        fail_load_non_registered_sybmols_build_file = dedent(
            """
            # We try to load a macro file that itself has load() statements,
            # Some of which are not registered with pants.
            load("examples/src/scala/org/pantsbuild/example/build_file_macros/MACRO_THAT_LOADS_NON_REGISTERED_MACROS")

            target(name="dummy")
            """
        )

        with self._mock_broken_project_dir(fail_load_non_registered_sybmols_build_file) as tmpdir:
            pants_run = self.do_command("list", f"{tmpdir}:", success=False,)
            print(f"BL: asdfsdf{pants_run.stderr_data}")
            assert (
                "File examples/src/scala/org/pantsbuild/example/build_file_macros/MACRO_THAT_LOADS_NON_REGISTERED_MACROS "
                "is trying to load() sybmols ['non_registered_symbol'], which are not registered with pants. "
                "This is not allowed for now, please stick to loading only registered symbols."
                in pants_run.stderr_data
            )

    def test_loads_dont_pollute_other_files(self):
        fail_to_load_symbols_build_file = dedent(
            """
            # source_exe_scala should come from this file, but we don't expose it.
            load("examples/src/scala/org/pantsbuild/example/build_file_macros/BUILD_MACROS_2")

            jvm_binary(
              main="org.pantsbuild.example.build_file_macros.Exe",
              sources=source_exe_scala(),
            )
            """
        )
        with self._mock_broken_project_dir(fail_to_load_symbols_build_file) as tmpdir:
            pants_run = self.do_command(
                "list",
                "examples/src/scala/org/pantsbuild/example/build_file_macros",
                f"{tmpdir}",
                success=False,
            )
            assert "name 'source_exe_scala' is not defined" in pants_run.stderr_data

    def test_changing_macro_file_invalidates_build_parsing(self):
        # Create a BUILD file in a nested temporary directory, and add additional targets to it.
        with self.pantsd_successful_run_context() as (pantsd_run, checker, _, _), temporary_dir(
            root_dir=get_buildroot()
        ) as tmpdir:

            rel_tmpdir = fast_relpath(tmpdir, get_buildroot())

            macro_file_path = os.path.join(rel_tmpdir, "BUILD_MACRO")

            safe_file_dump(
                os.path.join(tmpdir, "BUILD"),
                dedent(
                    f"""
                load("{macro_file_path}", "my_name")
                target(name=my_name())
                """
                ),
            )

            def change_name_macro_and_run_list(name):
                safe_file_dump(macro_file_path, f"def my_name(): return '{name}'")

                daemon_run = pantsd_run(["list", f"{rel_tmpdir}::"])
                checker.assert_running()

                assert f"{rel_tmpdir}:{name}" in daemon_run.stdout_data

            # Replace the BUILD file content twice.
            change_name_macro_and_run_list("name_one")
            checker.assert_running()
            change_name_macro_and_run_list("name_two")
