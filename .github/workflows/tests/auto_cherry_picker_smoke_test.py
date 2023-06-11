# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import subprocess
from textwrap import dedent

import pytest


@pytest.fixture(scope="session", autouse=True)
def stub_make_pr():
    with open("build-support/cherry_pick/make_pr.sh", "w") as f:
        f.write(
            dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail

                echo "make_pr.sh $@"
                # We exit 1 to test we still call the finish job
                exit 1
                """
            )
        )


@pytest.fixture(scope="session", autouse=True)
def stub_helper():
    with open("build-support/cherry_pick/helper.js", "w") as f:
        f.write(
            dedent(
                """\
                class CherryPickHelper {
                    constructor({ octokit, context, core }) {}
                    async get_prereqs() {
                        return {
                            pr_num: 12345,
                            merge_commit: "ABCDEF12345",
                            milestones: ["2.16.x", "2.17.x"],
                        };
                    }

                    async cherry_pick_finished(merge_commit_sha, matrix_info) {
                        console.log(`cherry_picked_finished: ${merge_commit_sha} ${JSON.stringify(matrix_info)}`);
                    }
                };

                module.exports = CherryPickHelper;
                """
            )
        )


def test_auto_cherry_pick():
    result = subprocess.run(
        [
            "./act",
            "workflow_dispatch",
            "-W",
            ".github/workflows/auto-cherry-picker.yaml",
            "--input",
            "PR_number=17295",
            "--env",
            "GITHUB_REPOSITORY=pantsbuild/pants",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = result.stdout
    print(stdout)
    assert "make_pr.sh 12345 2.16.x" in stdout
    assert "make_pr.sh 12345 2.17.x" in stdout
    assert 'cherry_picked_finished: ABCDEF12345 [{"milestone":"2.16.x","branch_name":"cherry-pick-12345-to-2.16.x"},{"milestone":"2.17.x","branch_name":"cherry-pick-12345-to-2.17.x"}]' in stdout
