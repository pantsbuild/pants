# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
import itertools
import json
import os
import shutil
import time
import traceback
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from textwrap import dedent
from typing import Any

from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.gather_sources import GatherSources
from pants.backend.python.tasks.pytest_prep import PytestPrep
from pants.backend.python.tasks.python_execution_task_base import ensure_interpreter_search_path_env
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import ErrorWhileTesting, TaskError
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.base.hash_utils import Sharder
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.target import Target
from pants.task.task import Task
from pants.task.testrunner_task_mixin import PartitionedTestRunnerTaskMixin, TestResult
from pants.util.contextutil import environment_as, pushd, temporary_dir, temporary_file
from pants.util.dirutil import mergetree, safe_mkdir, safe_mkdir_for
from pants.util.memo import memoized_method, memoized_property
from pants.util.process_handler import SubprocessProcessHandler
from pants.util.strutil import safe_shlex_join
from pants.util.xml_parser import XmlParser


@dataclass(frozen=True)
class _Workdirs:
    root_dir: Any
    partition: Any

    @classmethod
    def for_partition(cls, work_dir, partition):
        root_dir = os.path.join(work_dir, Target.maybe_readable_identify(partition))
        safe_mkdir(root_dir, clean=False)
        return cls(root_dir=root_dir, partition=partition)

    @memoized_method
    def target_set_id(self, *targets):
        return Target.maybe_readable_identify(targets or self.partition)

    @memoized_method
    def junitxml_path(self, *targets):
        xml_path = os.path.join(
            self.root_dir, "junitxml", "TEST-{}.xml".format(self.target_set_id(*targets))
        )
        safe_mkdir_for(xml_path)
        return xml_path

    @memoized_property
    def coverage_path(self):
        coverage_workdir = os.path.join(self.root_dir, "coverage")
        safe_mkdir(coverage_workdir)
        return coverage_workdir

    def files(self):
        def files_iter():
            for dir_path, _, file_names in os.walk(self.root_dir):
                for filename in file_names:
                    yield os.path.join(dir_path, filename)

        return list(files_iter())


# TODO: convert this into an enum!
class PytestResult(TestResult):
    _SUCCESS_EXIT_CODES = (
        0,
        # This is returned by pytest when no tests are collected (EXIT_NOTESTSCOLLECTED).
        # We already short-circuit test runs with no test _targets_ to return 0 emulated exit codes and
        # we should do the same for cases when there are test targets but tests themselves have been
        # de-selected out of band via `pytest -k`.
        5,
    )

    @classmethod
    def _map_exit_code(cls, value):
        return 0 if value in cls._SUCCESS_EXIT_CODES else value


class PytestRun(PartitionedTestRunnerTaskMixin, Task):
    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("PytestRun", 3)]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        # NB: We always produce junit xml privately, and if this option is specified, we then copy
        # it to the user-specified directory, post any interaction with the cache to retrieve the
        # privately generated and cached xml files. As such, this option is not part of the
        # fingerprint.
        register(
            "--junit-xml-dir",
            metavar="<DIR>",
            help="Specifying a directory causes junit xml results files to be emitted under "
            "that dir for each test run.",
        )

        register(
            "--profile",
            metavar="<FILE>",
            fingerprint=True,
            help="Specifying a file path causes tests to be profiled with the profiling data "
            "emitted to that file (prefix). Note that tests may run in a different cwd, so "
            "it's best to use an absolute path to make it easy to find the subprocess "
            "profiles later.",
        )

        register(
            "--coverage",
            fingerprint=True,
            help="Emit coverage information for specified packages or directories (absolute or "
            'relative to the build root).  The special value "auto" indicates that Pants '
            "should attempt to deduce which packages to emit coverage for.",
        )
        register(
            "--coverage-include-test-sources",
            fingerprint=True,
            type=bool,
            help="Whether to include test source files in coverage measurement.",
        )
        register(
            "--coverage-reports",
            fingerprint=True,
            choices=("xml", "html"),
            type=list,
            member_type=str,
            default=("xml", "html"),
            help="Which coverage reports to emit.",
        )
        # For a given --coverage specification (which is fingerprinted), we will always copy the
        # associated generated and cached --coverage files to this directory post any interaction with
        # the cache to retrieve the coverage files. As such, this option is not part of the fingerprint.
        register(
            "--coverage-output-dir",
            metavar="<DIR>",
            default=None,
            help="Directory to emit coverage reports to. "
            "If not specified, a default within dist is used.",
        )

        register(
            "--test-shard",
            fingerprint=True,
            help="Subset of tests to run, in the form M/N, 0 <= M < N. For example, 1/3 means "
            "run tests number 2, 5, 8, 11, ...",
        )

        register(
            "--extra-pythonpath",
            type=list,
            fingerprint=True,
            advanced=True,
            help="Add these entries to the PYTHONPATH when running the tests. "
            "Useful for attaching to debuggers in test code.",
        )

    @classmethod
    def supports_passthru_args(cls):
        return True

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data(PytestPrep.PytestBinary)

    def _test_target_filter(self):
        def target_filter(target):
            return isinstance(target, PythonTests)

        return target_filter

    def _validate_target(self, target):
        pass

    class InvalidShardSpecification(TaskError):
        """Indicates an invalid `--test-shard` option."""

    DEFAULT_COVERAGE_CONFIG = dedent(
        """
        [run]
        branch = True
        timid = False
    
        [report]
        exclude_lines =
            def __repr__
            raise NotImplementedError
        """
    )

    @staticmethod
    def _format_string_list(values):
        # The coverage rc ini files accept "Multi-valued strings" - ie: lists of strings - denoted by
        # indenting values on multiple lines like so:
        # [section]
        # name =
        #   value1
        #   value2
        #
        # See http://nedbatchelder.com/code/coverage/config.html for details.
        return "\n\t{values}".format(values="\n\t".join(values))

    @staticmethod
    def _ensure_section(cp, section):
        if not cp.has_section(section):
            cp.add_section(section)

    # N.B.: Extracted for tests.
    @classmethod
    def _add_plugin_config(cls, cp, src_chroot_path, srcs_to_omit, src_to_target_base):
        # We use a coverage plugin to map PEX chroot source paths back to their original repo paths for
        # report output.
        plugin_module = PytestPrep.PytestBinary.coverage_plugin_module
        cls._ensure_section(cp, "run")
        cp.set("run", "plugins", plugin_module)

        if srcs_to_omit:
            # It would be nice if we could use the `include` setting to specify just the
            # files we *do* want to trace. But unfortunately that setting is ignored if `sources`
            # are explicitly specified, which pytest-cov does. And those `sources` must be packages or
            # directories, not individual files, so we can't use that either (in case there are
            # tests in the same dirs as the files they test).
            files_to_omit = [
                os.path.join(src_chroot_path, relpath) for relpath in sorted(srcs_to_omit)
            ]
            cp.set("run", "omit", ",".join(files_to_omit))

        # Fortunately we *can* use the `include` setting at report time. Any omitted files won't
        # have any data and won't get reported anyway. But setting `include` here allows us to also
        # exclude synthetic __init__.py files created by pex in the chroot. Reporting on those is just
        # confusing to the user, since they don't correspond to any file in the source tree.
        cls._ensure_section(cp, "report")
        files_to_report = [os.path.join(src_chroot_path, relpath) for relpath in src_to_target_base]
        cp.set("report", "include", ",".join(files_to_report))

        cp.add_section(plugin_module)
        cp.set(plugin_module, "buildroot", get_buildroot())
        cp.set(plugin_module, "src_chroot_path", src_chroot_path)
        cp.set(plugin_module, "src_to_target_base", json.dumps(src_to_target_base))

    def _generate_coverage_config(self, srcs_to_omit, src_to_target_base):
        cp = configparser.ConfigParser()
        cp.read_file(StringIO(self.DEFAULT_COVERAGE_CONFIG))

        self._add_plugin_config(cp, self._source_chroot_path, srcs_to_omit, src_to_target_base)

        # See the debug options here: http://nedbatchelder.com/code/coverage/cmd.html#cmd-run-debug
        if self.debug:
            debug_options = self._format_string_list(
                [
                    # Dumps the coverage config realized values.
                    "config",
                    # Logs which files are skipped or traced and why.
                    "trace",
                ]
            )
            self._ensure_section(cp, "run")
            cp.set("run", "debug", debug_options)

        return cp

    @staticmethod
    def _is_coverage_env_var(name):
        return name.startswith("COV_CORE_") or name.startswith(  # These are from `pytest-cov`.
            "COVERAGE_"
        )  # These are from `coverage`.

    @contextmanager
    def _scrub_cov_env_vars(self):
        cov_env_vars = {k: v for k, v in os.environ.items() if self._is_coverage_env_var(k)}
        if cov_env_vars:
            self.context.log.warn(
                "Scrubbing coverage environment variables\n\t{}".format(
                    "\n\t".join(sorted(f"{k}={v}" for k, v in cov_env_vars.items()))
                )
            )
            with environment_as(**{k: None for k in cov_env_vars}):
                yield
        else:
            yield

    @contextmanager
    def _cov_setup(self, workdirs, coverage_morfs, srcs_to_omit, src_to_target_base):
        cp = self._generate_coverage_config(
            srcs_to_omit=srcs_to_omit, src_to_target_base=src_to_target_base
        )
        # Note that it's important to put the tmpfile under the workdir, because pytest
        # uses all arguments that look like paths to compute its rootdir, and we want
        # it to pick the buildroot.
        with temporary_file(root_dir=workdirs.root_dir, binary_mode=False) as fp:
            cp.write(fp)
            fp.close()
            coverage_rc = fp.name
            # Note that --cov-report= with no value turns off terminal reporting, which
            # we handle separately.
            args = ["--cov-report=", "--cov-config", coverage_rc]
            for morf in coverage_morfs:
                args.extend(["--cov", morf])

            with self._scrub_cov_env_vars():
                yield args, coverage_rc

    @contextmanager
    def _maybe_emit_coverage_data(self, workdirs, test_targets, pex):
        coverage = self.get_options().coverage
        if coverage is None:
            yield []
            return

        pex_src_root = os.path.relpath(self._source_chroot_path, get_buildroot())

        src_to_target_base = {}
        srcs_to_omit = set()
        if not self.get_options().coverage_include_test_sources:
            for test_target in test_targets:
                srcs_to_omit.update(test_target.sources_relative_to_source_root())
        for test_target in test_targets:
            libs = (tgt for tgt in test_target.closure() if tgt.has_sources(".py"))
            for lib in libs:
                for src in lib.sources_relative_to_source_root():
                    if src not in srcs_to_omit:
                        src_to_target_base[src] = lib.target_base

        def ensure_trailing_sep(path):
            return path if path.endswith(os.path.sep) else path + os.path.sep

        if coverage == "auto":

            def compute_coverage_pkgs(tgt):
                if tgt.coverage:
                    return tgt.coverage
                else:
                    # Assume that tests in some package test the sources in that package.
                    # This is the case, e.g., if tests live in the same directories as the sources
                    # they test, or if they live in a parallel package structure under a separate
                    # source root, such as tests/python/path/to/package testing src/python/path/to/package.

                    # Note in particular that this doesn't work for most of Pants's own tests, as those are
                    # under the top level package 'pants_tests', rather than just 'pants' (although we
                    # are moving towards having tests in the same directories as the sources they test).
                    #
                    # TODO(John Sirois): consider failing fast if there is no explicit coverage scheme;
                    # but also  consider supporting configuration of a global scheme whether that be parallel
                    # dirs/packages or some arbitrary function that can be registered that takes a test target
                    # and hands back the source packages or paths under test.
                    def package(test_source_path):
                        return os.path.dirname(test_source_path).replace(os.sep, ".")

                    def packages():
                        for test_source_path in tgt.sources_relative_to_source_root():
                            pkg = package(test_source_path)
                            if pkg:
                                yield pkg

                    return packages()

            coverage_morfs = set(itertools.chain(*[compute_coverage_pkgs(t) for t in test_targets]))
        else:
            coverage_morfs = []
            for morf in coverage.split(","):
                if os.path.isdir(morf):
                    # The source is a dir, so correct its prefix for the chroot.
                    # E.g. if source is /path/to/src/python/foo/bar or src/python/foo/bar then
                    # rel_source is src/python/foo/bar, and ...
                    rel_source = os.path.relpath(morf, get_buildroot())
                    rel_source = ensure_trailing_sep(rel_source)

                    found_target_base = False
                    for target_base in set(src_to_target_base.values()):
                        prefix = ensure_trailing_sep(target_base)
                        if rel_source.startswith(prefix):
                            # ... rel_source will match on prefix=src/python/ ...
                            suffix = rel_source[len(prefix) :]
                            # ... suffix will equal foo/bar ...
                            coverage_morfs.append(
                                os.path.join(get_buildroot(), pex_src_root, suffix)
                            )
                            found_target_base = True
                            # ... and we end up appending <pex_src_root>/foo/bar to the coverage_sources.
                            break
                    if not found_target_base:
                        self.context.log.warn(
                            f"Coverage path {morf} is not in any target. Skipping."
                        )
                else:
                    # The source is to be interpreted as a package name.
                    coverage_morfs.append(morf)

        with self._cov_setup(
            workdirs,
            coverage_morfs=coverage_morfs,
            srcs_to_omit=srcs_to_omit,
            src_to_target_base=src_to_target_base,
        ) as (args, coverage_rc):
            try:
                yield args
            finally:
                env = {"PEX_MODULE": "coverage.cmdline:main"}

                def coverage_run(subcommand, arguments):
                    return self._pex_run(
                        pex,
                        workunit_name=f"coverage-{subcommand}",
                        args=[subcommand] + arguments,
                        env=env,
                    )

                # The '.coverage' data file is output in the CWD of the test run above; so we make sure to
                # look for it there.
                with self._maybe_run_in_chroot():
                    # On failures or timeouts, the .coverage file won't be written.
                    if not os.path.exists(".coverage"):
                        self.context.log.warn(
                            "No .coverage file was found! Skipping coverage reporting."
                        )
                    else:
                        coverage_workdir = workdirs.coverage_path
                        coverage_reports = self.get_options().coverage_reports
                        if "html" in coverage_reports:
                            coverage_run(
                                "html", ["-i", "--rcfile", coverage_rc, "-d", coverage_workdir]
                            )
                        if "xml" in coverage_reports:
                            coverage_xml = os.path.join(coverage_workdir, "coverage.xml")
                            coverage_run("xml", ["-i", "--rcfile", coverage_rc, "-o", coverage_xml])

    def _get_sharding_args(self):
        shard_spec = self.get_options().test_shard
        if shard_spec is None:
            return []

        try:
            sharder = Sharder(shard_spec)
            return ["--pants-shard", f"{sharder.shard}", "--pants-num-shards", f"{sharder.nshards}"]
        except Sharder.InvalidShardSpec as e:
            raise self.InvalidShardSpecification(e)

    @contextmanager
    def _pants_pytest_plugin_args(self, sources_map):
        """Configures the pants pytest plugin to customize our pytest run."""
        # Note that it's important to put the tmpdir under the workdir, because pytest
        # uses all arguments that look like paths to compute its rootdir, and we want
        # it to pick the buildroot.
        with temporary_dir(root_dir=self.workdir) as comm_dir:
            sources_map_path = os.path.join(comm_dir, "sources_map.json")
            with open(sources_map_path, "w") as fp:
                json.dump(sources_map, fp)

            renaming_args = ["--pants-sources-map-path", sources_map_path]

            yield renaming_args + self._get_sharding_args()

    @contextmanager
    def _test_runner(self, workdirs, test_targets, sources_map):
        pytest_binary = self.context.products.get_data(PytestPrep.PytestBinary)
        with self._pants_pytest_plugin_args(sources_map) as plugin_args:
            with self._maybe_emit_coverage_data(
                workdirs, test_targets, pytest_binary.pex
            ) as coverage_args:
                pytest_rootdir = get_buildroot()
                yield (
                    pytest_binary,
                    ["--rootdir", pytest_rootdir, "-p", pytest_binary.pytest_plugin_module]
                    + plugin_args
                    + coverage_args,
                    pytest_rootdir,
                )

    def _ensure_pytest_interpreter_search_path(self):
        """Return an environment for invoking a pex which ensures the use of the selected
        interpreter.

        When creating the merged pytest pex, we already have an interpreter, and we only invoke that
        pex within a pants run, so we can be sure the selected interpreter will be available.
        Constraining the interpreter search path at pex runtime ensures that any resolved
        requirements will be compatible with the interpreter being used to invoke the merged pytest
        pex.
        """
        pytest_binary = self.context.products.get_data(PytestPrep.PytestBinary)
        return ensure_interpreter_search_path_env(pytest_binary.interpreter)

    def _do_run_tests_with_args(self, test_targets, pex, args):
        try:
            env = dict(os.environ)

            # Allow this back door for users who do want to force something onto the test pythonpath,
            # e.g., modules required during a debugging session.
            extra_pythonpath = self.get_options().extra_pythonpath
            if extra_pythonpath:
                env["PYTHONPATH"] = os.pathsep.join(extra_pythonpath)
                env["PEX_INHERIT_PATH"] = "prefer"

            # The pytest runner we use accepts a --pdb argument that will launch an interactive pdb
            # session on any test failure.  In order to support use of this pass-through flag we must
            # turn off stdin buffering that otherwise occurs.  Setting the PYTHONUNBUFFERED env var to
            # any value achieves this in python2.7.  We'll need a different solution when we support
            # running pants under CPython 3 which does not unbuffer stdin using this trick.
            env["PYTHONUNBUFFERED"] = "1"

            # pytest uses py.io.terminalwriter for output. That class detects the terminal
            # width and attempts to use all of it. However we capture and indent the console
            # output, leading to weird-looking line wraps. So we trick the detection code
            # into thinking the terminal window is narrower than it is.
            env["COLUMNS"] = str(int(os.environ.get("COLUMNS", 80)) - 30)

            profile = self.get_options().profile
            if profile:
                env["PEX_PROFILE_FILENAME"] = f"{profile}.subprocess.{time.time():.6f}"

            with self.context.new_workunit(
                name="run",
                cmd=safe_shlex_join(pex.cmdline(args)),
                labels=[WorkUnitLabel.TOOL, WorkUnitLabel.TEST],
            ) as workunit:
                # NB: Constrain the pex environment to ensure the use of the selected interpreter!
                env.update(self._ensure_pytest_interpreter_search_path())
                rc = self.spawn_and_wait(
                    test_targets, pex, workunit=workunit, args=args, setsid=True, env=env
                )
                return PytestResult.rc(rc)
        except ErrorWhileTesting:
            # spawn_and_wait wraps the test runner in a timeout, so it could
            # fail with a ErrorWhileTesting. We can't just set PythonTestResult
            # to a failure because the resultslog doesn't have all the failures
            # when tests are killed with a timeout. Therefore we need to re-raise
            # here.
            raise
        except Exception:
            self.context.log.error("Failed to run test!")
            self.context.log.info(traceback.format_exc())
            return PytestResult.exception()

    def _map_relsrc_to_targets(self, targets):
        pex_src_root = os.path.relpath(self._source_chroot_path, get_buildroot())
        # First map chrooted sources back to their targets.
        relsrc_to_target = {
            os.path.join(pex_src_root, src): target
            for target in targets
            for src in target.sources_relative_to_source_root()
        }
        # Also map the source tree-rooted sources, because in some cases (e.g., a failure to even
        # eval the test file during test collection), that's the path pytest will use in the junit xml.
        relsrc_to_target.update(
            {src: target for target in targets for src in target.sources_relative_to_buildroot()}
        )

        return relsrc_to_target

    def _get_failed_targets_from_junitxml(self, junitxml, targets, pytest_rootdir):
        relsrc_to_target = self._map_relsrc_to_targets(targets)
        buildroot_relpath = os.path.relpath(pytest_rootdir, get_buildroot())

        # Now find the sources that contained failing tests.
        failed_targets = set()

        try:
            xml = XmlParser.from_file(junitxml)
            failures = int(xml.get_attribute("testsuite", "failures"))
            errors = int(xml.get_attribute("testsuite", "errors"))
            if failures or errors:
                for testcase in xml.parsed.getElementsByTagName("testcase"):
                    test_failed = testcase.getElementsByTagName("failure")
                    test_errored = testcase.getElementsByTagName("error")
                    if test_failed or test_errored:
                        # The file attribute is always relative to the pytest rootdir.
                        pytest_relpath = testcase.getAttribute("file")
                        relsrc = os.path.normpath(os.path.join(buildroot_relpath, pytest_relpath))
                        failed_target = relsrc_to_target.get(relsrc)
                        if failed_target:
                            failed_targets.add(failed_target)
                        else:
                            # If test failure/error was not reported in junitxml, pick the first test target
                            # in targets as the failed target
                            failed_targets.add(targets[0])
        except (XmlParser.XmlError, ValueError) as e:
            raise TaskError(f"Error parsing xml file at {junitxml}: {e!r}")

        return failed_targets

    def _get_target_from_test(self, test_info, targets, pytest_rootdir):
        relsrc_to_target = self._map_relsrc_to_targets(targets)
        buildroot_relpath = os.path.relpath(pytest_rootdir, get_buildroot())
        pytest_relpath = test_info["file"]
        relsrc = os.path.normpath(os.path.join(buildroot_relpath, pytest_relpath))
        return relsrc_to_target.get(relsrc)

    @contextmanager
    def partitions(self, per_target, all_targets, test_targets):
        if per_target:

            def iter_partitions():
                for test_target in test_targets:
                    yield (test_target,)

        else:

            def iter_partitions():
                yield tuple(test_targets)

        workdir = self.workdir

        def iter_partitions_with_args():
            for partition in iter_partitions():
                workdirs = _Workdirs.for_partition(workdir, partition)
                args = (workdirs,)
                yield partition, args

        yield iter_partitions_with_args

    # TODO(John Sirois): Its probably worth generalizing a means to mark certain options or target
    # attributes as making results un-cacheable. See: https://github.com/pantsbuild/pants/issues/4748
    class NeverCacheFingerprintStrategy(DefaultFingerprintStrategy):
        def compute_fingerprint(self, target):
            return uuid.uuid4()

    def fingerprint_strategy(self):
        if self.get_options().profile:
            # A profile is machine-specific and we assume anyone wanting a profile wants to run it here
            # and now and not accept some old result, even if on the same inputs.
            return self.NeverCacheFingerprintStrategy()
        else:
            return None  # Accept the default fingerprint strategy.

    def run_tests(self, fail_fast, test_targets, workdirs):
        try:
            return self._run_pytest(fail_fast, tuple(test_targets), workdirs)
        finally:
            # Unconditionally pluck any results that an end user might need to interact with from the
            # workdir to the locations they expect.
            self._expose_results(test_targets, workdirs)

    @memoized_property
    def result_class(self):
        return PytestResult

    def collect_files(self, workdirs):
        return workdirs.files()

    def _expose_results(self, invalid_tgts, workdirs):
        external_junit_xml_dir = self.get_options().junit_xml_dir
        if external_junit_xml_dir:
            safe_mkdir(external_junit_xml_dir)

            junitxml_path = workdirs.junitxml_path(*invalid_tgts)
            if os.path.exists(junitxml_path):
                # Either we just ran pytest for a set of invalid targets and generated a junit xml file
                # specific to that (sub)set or else we hit the cache for the whole partition and skipped
                # running pytest, simply retrieving the partition's full junit xml file.
                shutil.copy2(junitxml_path, external_junit_xml_dir)

        if self.get_options().coverage:
            coverage_output_dir = self.get_options().coverage_output_dir
            if coverage_output_dir:
                target_dir = coverage_output_dir
            else:
                pants_distdir = self.context.options.for_global_scope().pants_distdir
                relpath = workdirs.target_set_id()
                target_dir = os.path.join(pants_distdir, "coverage", relpath)
            mergetree(workdirs.coverage_path, target_dir)

    def _run_pytest(self, fail_fast, test_targets, workdirs):
        if not test_targets:
            return PytestResult.rc(0)

        # Absolute path to chrooted test file -> Path to original test file relative to the buildroot.
        sources_map = OrderedDict()
        for t in test_targets:
            for p in t.sources_relative_to_source_root():
                sources_map[os.path.join(self._source_chroot_path, p)] = os.path.join(
                    t.target_base, p
                )

        if not sources_map:
            return PytestResult.rc(0)

        with self._test_runner(workdirs, test_targets, sources_map) as (
            pytest_binary,
            test_args,
            pytest_rootdir,
        ):
            # Validate that the user didn't provide any passthru args that conflict
            # with those we must set ourselves.
            for arg in (*self.get_passthru_args(), *PyTest.global_instance().options.args):
                if arg.startswith("--junitxml") or arg.startswith("--confcutdir"):
                    raise TaskError(f"Cannot pass this arg through to pytest: {arg}")

            junitxml_path = workdirs.junitxml_path(*test_targets)

            # N.B. the `--confcutdir` here instructs pytest to stop scanning for conftest.py files at the
            # top of the buildroot. This prevents conftest.py files from outside (e.g. in users home dirs)
            # from leaking into pants test runs. See: https://github.com/pantsbuild/pants/issues/2726
            args = [
                "-c",
                os.devnull,  # Force an empty pytest.ini
                "-o" "cache_dir={}".format(os.path.join(self.workdir, ".pytest_cache")),
                "--junitxml",
                junitxml_path,
                "--confcutdir",
                get_buildroot(),
                "--continue-on-collection-errors",
            ]
            if fail_fast:
                args.extend(["-x"])
            if self.debug:
                args.extend(["-s"])
            if self.get_options().colors:
                args.extend(["--color", "yes"])

            # NB: While passthrough args are not supported in v2 yet, as discussed on #9075, it seems
            # likely that we can find a way to preserve the ability to use passthrough args for
            # umabiguous goals in v2.
            args.extend([*self.get_passthru_args(), *PyTest.global_instance().options.args])

            args.extend(test_args)
            args.extend(sources_map.keys())

            # We want to ensure our reporting based off junit xml is from this run so kill results from
            # prior runs.
            if os.path.exists(junitxml_path):
                os.unlink(junitxml_path)

            with self._maybe_run_in_chroot():
                result = self._do_run_tests_with_args(test_targets, pytest_binary.pex, args)

            # There was a problem prior to test execution preventing junit xml file creation so just let
            # the failure result bubble.
            if not os.path.exists(junitxml_path):
                return result

            failed_targets = self._get_failed_targets_from_junitxml(
                junitxml_path, test_targets, pytest_rootdir
            )

            def parse_error_handler(parse_error):
                # Simple error handler to pass to xml parsing function.
                raise TaskError(
                    "Error parsing xml file at {}: {}".format(
                        parse_error.xml_path, parse_error.cause
                    )
                )

            all_tests_info = self.parse_test_info(
                junitxml_path, parse_error_handler, ["file", "name", "classname"]
            )
            for test_name, test_info in all_tests_info.items():
                test_target = self._get_target_from_test(test_info, test_targets, pytest_rootdir)
                self.report_all_info_for_single_test(
                    self.options_scope, test_target, test_name, test_info
                )

            return result.with_failed_targets(failed_targets)

    @memoized_property
    def _source_chroot_path(self):
        return self.context.products.get_data(GatherSources.PYTHON_SOURCES).path()

    def _pex_run(self, pex, workunit_name, args, env):
        with self.context.new_workunit(
            name=workunit_name,
            cmd=" ".join(pex.cmdline(args)),
            labels=[WorkUnitLabel.TOOL, WorkUnitLabel.TEST],
        ) as workunit:
            # NB: Constrain the pex environment to ensure the use of the selected interpreter!
            env.update(self._ensure_pytest_interpreter_search_path())
            process = self._spawn(pex, workunit, args, setsid=False, env=env)
            return process.wait()

    @contextmanager
    def _maybe_run_in_chroot(self):
        if self.run_tests_in_chroot:
            with pushd(self._source_chroot_path):
                yield
        else:
            yield

    def _spawn(self, pex, workunit, args, setsid=False, env=None):
        env = env or {}
        process = pex.run(
            args,
            with_chroot=False,  # We handle chrooting ourselves.
            blocking=False,
            setsid=setsid,
            env=env,
            stdout=workunit.output("stdout"),
            stderr=workunit.output("stderr"),
        )
        return SubprocessProcessHandler(process)
