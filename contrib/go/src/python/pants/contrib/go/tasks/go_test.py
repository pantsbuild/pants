# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from contextlib import contextmanager
from dataclasses import dataclass

from pants.base.build_environment import get_buildroot
from pants.base.workunit import WorkUnitLabel
from pants.task.testrunner_task_mixin import ChrootedTestRunnerTaskMixin, TestResult
from pants.util.memo import memoized_property
from pants.util.process_handler import SubprocessProcessHandler
from pants.util.strutil import create_path_env_var, safe_shlex_join, safe_shlex_split

from pants.contrib.go.tasks.go_workspace_task import GoWorkspaceTask


class GoTest(ChrootedTestRunnerTaskMixin, GoWorkspaceTask):
    """Runs `go test` on Go packages.

    To run a library's tests, GoTest only requires a Go workspace to be initialized (see
    GoWorkspaceTask) with links to necessary source files. It does not require GoCompile to first
    compile the library to be tested -- in fact, GoTest will ignore any binaries in "$GOPATH/pkg/",
    because Go test files (which live in the package they are testing) are ignored in normal
    compilation, so Go test must compile everything from scratch.
    """

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        # TODO: make a shlexed flags option type!
        register(
            "--shlexed-build-and-test-flags",
            type=list,
            member_type=str,
            fingerprint=True,
            help="Flags to pass in to `go test` tool. Each string is parsed as a shell would, "
            "respecting quotes and backslashes.",
        )

    @classmethod
    def supports_passthru_args(cls):
        return True

    def _test_target_filter(self):
        """Filter for go library targets (in the target closure) with test files."""
        return self.is_test_target

    def _validate_target(self, target):
        self.ensure_workspace(target)

    @dataclass(frozen=True)
    class _GoTestTargetInfo:
        import_path: str
        gopath: str

    def _generate_args_for_targets(self, targets):
        """Generate a dict mapping target -> _GoTestTargetInfo so that the import path and gopath
        can be reconstructed for spawning test commands regardless of how the targets are
        partitioned."""
        return {
            t: self._GoTestTargetInfo(import_path=t.import_path, gopath=self.get_gopath(t))
            for t in targets
        }

    @contextmanager
    def tests(self, all_targets, test_targets):
        def iter_tests():
            for test_target in test_targets:
                args = (self._generate_args_for_targets([test_target]),)
                yield test_target, args

        yield iter_tests

    def collect_files(self, *args):
        """This task currently doesn't have any output that it would store in an artifact cache."""
        return []

    @memoized_property
    def _build_and_test_flags(self):
        return [
            single_flag
            for flags_section in self.get_options().shlexed_build_and_test_flags
            for single_flag in safe_shlex_split(flags_section)
        ]

    def _spawn(self, workunit, go_cmd, cwd):
        go_process = go_cmd.spawn(
            cwd=cwd, stdout=workunit.output("stdout"), stderr=workunit.output("stderr")
        )
        return SubprocessProcessHandler(go_process)

    @property
    def _maybe_workdir(self):
        if self.run_tests_in_chroot:
            return None
        return get_buildroot()

    def run_tests(self, fail_fast, test_targets, args_by_target):
        self.context.log.debug(f"test_targets: {test_targets}")

        with self.chroot(test_targets, self._maybe_workdir) as chroot:
            cmdline_args = (
                self._build_and_test_flags
                + [args_by_target[t].import_path for t in test_targets]
                + self.get_passthru_args()
            )
            gopath = create_path_env_var(args_by_target[t].gopath for t in test_targets)
            go_cmd = self.go_dist.create_go_cmd("test", gopath=gopath, args=cmdline_args)

            self.context.log.debug(f"go_cmd: {go_cmd}")

            workunit_labels = [WorkUnitLabel.TOOL, WorkUnitLabel.TEST]
            with self.context.new_workunit(
                name="go test", cmd=safe_shlex_join(go_cmd.cmdline), labels=workunit_labels
            ) as workunit:

                exit_code = self.spawn_and_wait(
                    test_targets, workunit=workunit, go_cmd=go_cmd, cwd=chroot
                )
                return TestResult.rc(exit_code)
