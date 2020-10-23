# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass

import pytest

from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    PathGlobs,
    Snapshot,
)
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import (
    BinaryPathRequest,
    BinaryPaths,
    FallibleProcessResult,
    InteractiveProcess,
    Process,
    ProcessResult,
)
from pants.engine.rules import Get, rule
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.testutil.test_base import TestBase
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, touch


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(BinaryPaths, [BinaryPathRequest]),
        ],
    )


@dataclass(frozen=True)
class Concatted:
    value: str


@dataclass(frozen=True)
class BinaryLocation:
    bin_path: str

    def __post_init__(self):
        if not os.path.isfile(self.bin_path) or not os.access(self.bin_path, os.X_OK):
            raise ValueError(f"path {self.bin_path} does not name an existing executable file.")


@dataclass(frozen=True)
class ShellCat:
    """Wrapper class to show an example of using an auxiliary class (which wraps an executable) to
    generate an argv instead of doing it all in CatExecutionRequest.

    This can be used to encapsulate operations such as sanitizing command-line arguments which are
    specific to the executable, which can reduce boilerplate for generating Process instances if the
    executable is used in different ways across multiple different types of process execution
    requests.
    """

    binary_location: BinaryLocation

    @property
    def bin_path(self):
        return self.binary_location.bin_path

    def argv_from_snapshot(self, snapshot):
        cat_file_paths = snapshot.files

        option_like_files = [p for p in cat_file_paths if p.startswith("-")]
        if option_like_files:
            raise ValueError(
                f"invalid file names: '{option_like_files}' look like command-line options"
            )

        # Add /dev/null to the list of files, so that cat doesn't hang forever if no files are in the
        # Snapshot.
        return (self.bin_path, "/dev/null") + tuple(cat_file_paths)


@dataclass(frozen=True)
class CatExecutionRequest:
    shell_cat: ShellCat
    path_globs: PathGlobs


@rule
async def cat_files_process_result_concatted(cat_exe_req: CatExecutionRequest) -> Concatted:
    cat_bin = cat_exe_req.shell_cat
    cat_files_snapshot = await Get(Snapshot, PathGlobs, cat_exe_req.path_globs)
    process = Process(
        argv=cat_bin.argv_from_snapshot(cat_files_snapshot),
        input_digest=cat_files_snapshot.digest,
        description="cat some files",
    )
    cat_process_result = await Get(ProcessResult, Process, process)
    return Concatted(cat_process_result.stdout.decode())


def cat_stdout_rules():
    return [cat_files_process_result_concatted, QueryRule(Concatted, (CatExecutionRequest,))]


class TestInputFileCreation(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            QueryRule(ProcessResult, (Process,)),
            QueryRule(FallibleProcessResult, (Process,)),
        )

    def test_input_file_creation(self):
        file_name = "some.filename"
        file_contents = b"some file contents"

        digest = self.request(
            Digest, [CreateDigest([FileContent(path=file_name, content=file_contents)])]
        )
        req = Process(
            argv=("/bin/cat", file_name),
            input_digest=digest,
            description="cat the contents of this file",
        )

        result = self.request(ProcessResult, [req])
        self.assertEqual(result.stdout, file_contents)

    def test_multiple_file_creation(self):
        digest = self.request(
            Digest,
            [
                CreateDigest(
                    (
                        FileContent(path="a.txt", content=b"hello"),
                        FileContent(path="b.txt", content=b"goodbye"),
                    )
                )
            ],
        )

        req = Process(
            argv=("/bin/cat", "a.txt", "b.txt"),
            input_digest=digest,
            description="cat the contents of this file",
        )

        result = self.request(ProcessResult, [req])
        self.assertEqual(result.stdout, b"hellogoodbye")

    def test_file_in_directory_creation(self):
        path = "somedir/filename"
        content = b"file contents"

        digest = self.request(Digest, [CreateDigest([FileContent(path=path, content=content)])])
        req = Process(
            argv=("/bin/cat", "somedir/filename"),
            input_digest=digest,
            description="Cat a file in a directory to make sure that doesn't break",
        )

        result = self.request(ProcessResult, [req])
        self.assertEqual(result.stdout, content)

    def test_not_executable(self):
        file_name = "echo.sh"
        file_contents = b'#!/bin/bash -eu\necho "Hello"\n'

        digest = self.request(
            Digest, [CreateDigest([FileContent(path=file_name, content=file_contents)])]
        )
        req = Process(
            argv=("./echo.sh",),
            input_digest=digest,
            description="cat the contents of this file",
        )

        with pytest.raises(ExecutionError) as exc:
            self.request(ProcessResult, [req])
        assert "Permission" in str(exc.value)

    def test_executable(self):
        file_name = "echo.sh"
        file_contents = b'#!/bin/bash -eu\necho "Hello"\n'

        digest = self.request(
            Digest,
            [
                CreateDigest(
                    [FileContent(path=file_name, content=file_contents, is_executable=True)]
                )
            ],
        )
        req = Process(
            argv=("./echo.sh",),
            input_digest=digest,
            description="cat the contents of this file",
        )

        result = self.request(ProcessResult, [req])
        self.assertEqual(result.stdout, b"Hello\n")


class ProcessTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *cat_stdout_rules(),
            QueryRule(ProcessResult, (Process,)),
            QueryRule(FallibleProcessResult, (Process,)),
        )

    def test_env(self):
        req = Process(argv=("foo",), description="Some process", env={"VAR": "VAL"})
        assert dict(req.env) == {"VAR": "VAL"}

    def test_integration_concat_with_snapshots_stdout(self):
        self.create_file("f1", "one\n")
        self.create_file("f2", "two\n")

        cat_exe_req = CatExecutionRequest(
            ShellCat(BinaryLocation("/bin/cat")),
            PathGlobs(["f*"]),
        )

        concatted = self.request(Concatted, [cat_exe_req])
        self.assertEqual(Concatted("one\ntwo\n"), concatted)

    def test_write_file(self):
        request = Process(
            argv=("/bin/bash", "-c", "echo -n 'European Burmese' > roland"),
            description="echo roland",
            output_files=("roland",),
        )

        process_result = self.request(ProcessResult, [request])

        self.assertEqual(
            process_result.output_digest,
            Digest(
                fingerprint="63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16",
                serialized_bytes_length=80,
            ),
        )

        digest_contents = self.request(DigestContents, [process_result.output_digest])
        assert digest_contents == DigestContents(
            [FileContent("roland", b"European Burmese", False)]
        )

    def test_timeout(self):
        request = Process(
            argv=("/bin/bash", "-c", "/bin/sleep 0.2; /bin/echo -n 'European Burmese'"),
            timeout_seconds=0.1,
            description="sleepy-cat",
        )
        result = self.request(FallibleProcessResult, [request])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn(b"Exceeded timeout", result.stdout)
        self.assertIn(b"sleepy-cat", result.stdout)

    def test_fallible_failing_command_returns_exited_result(self):
        request = Process(argv=("/bin/bash", "-c", "exit 1"), description="one-cat")

        result = self.request(FallibleProcessResult, [request])

        self.assertEqual(result.exit_code, 1)

    def test_non_fallible_failing_command_raises(self):
        request = Process(argv=("/bin/bash", "-c", "exit 1"), description="one-cat")

        with self.assertRaises(ExecutionError) as cm:
            self.request(ProcessResult, [request])
        assert "Process 'one-cat' failed with exit code 1." in str(cm.exception)


def test_running_interactive_process_in_workspace_cannot_have_input_files() -> None:
    mock_digest = Digest(EMPTY_DIGEST.fingerprint, 1)
    with pytest.raises(ValueError):
        InteractiveProcess(argv=["/bin/echo"], input_digest=mock_digest, run_in_workspace=True)


def test_find_binary_non_existent(rule_runner: RuleRunner) -> None:
    with temporary_dir() as tmpdir:
        search_path = [tmpdir]
        binary_paths = rule_runner.request(
            BinaryPaths, [BinaryPathRequest(binary_name="anybin", search_path=search_path)]
        )
        assert binary_paths.first_path is None


def test_find_binary_on_path_without_bash(rule_runner: RuleRunner) -> None:
    # Test that locating a binary on a PATH which does not include bash works (by recursing to
    # locate bash first).
    binary_name = "mybin"
    binary_dir = "bin"
    with temporary_dir() as tmpdir:
        binary_dir_abs = os.path.join(tmpdir, binary_dir)
        binary_path_abs = os.path.join(binary_dir_abs, binary_name)
        safe_mkdir(binary_dir_abs)
        touch(binary_path_abs)

        search_path = [binary_dir_abs]
        binary_paths = rule_runner.request(
            BinaryPaths, [BinaryPathRequest(binary_name=binary_name, search_path=search_path)]
        )
        assert os.path.exists(os.path.join(binary_dir_abs, binary_name))
        assert binary_paths.first_path is not None
        assert binary_paths.first_path.path == binary_path_abs
