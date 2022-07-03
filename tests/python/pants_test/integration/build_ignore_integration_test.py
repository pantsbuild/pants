# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_build_ignore_list() -> None:
    with setup_tmpdir({"dir/BUILD": "target()"}) as tmpdir:
        ignore_result = run_pants([f"--build-ignore={tmpdir}/dir", "list", f"{tmpdir}/dir:dir"])
        no_ignore_result = run_pants(["list", f"{tmpdir}/dir:dir"])
    ignore_result.assert_failure()
    assert f"{tmpdir}/dir" in ignore_result.stderr
    no_ignore_result.assert_success()
    assert f"{tmpdir}/dir" in no_ignore_result.stdout


def test_build_ignore_dependency() -> None:
    sources = {
        "dir1/f.txt": "",
        "dir1/BUILD": "files(sources=['*.txt'])",
        "dir2/f.txt": "",
        "dir2/BUILD": "files(sources=['*.txt'], dependencies=['{tmpdir}/dir1'])",
    }
    with setup_tmpdir(sources) as tmpdir:
        ignore_result = run_pants(
            [f"--build-ignore={tmpdir}/dir1", "dependencies", f"{tmpdir}/dir2/f.txt"]
        )
        no_ignore_result = run_pants(["dependencies", f"{tmpdir}/dir2/f.txt"])
    ignore_result.assert_failure()
    assert f"{tmpdir}/dir1" in ignore_result.stderr
    no_ignore_result.assert_success()
    assert f"{tmpdir}/dir1" in no_ignore_result.stdout
