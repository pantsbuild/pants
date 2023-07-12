# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import os
import shlex
import subprocess

import github
from pants_release.common import die, green

logger = logging.getLogger(__name__)

MAIN_REPO_SLUG = "pantsbuild/pants"
MAIN_REPO = f"https://github.com/{MAIN_REPO_SLUG}"

GH_TOKEN_VAR_NAME = "GH_TOKEN"


def _run(
    exe: str,
    args: tuple[None | str, ...],
    check: bool,
    capture_stdout: bool,
) -> str:
    cmd = [exe, *(a for a in args if a is not None)]
    logger.info("running: %s", shlex.join(cmd))
    result = subprocess.run(
        cmd,
        check=check,
        stdout=subprocess.PIPE if capture_stdout else None,
        text=True,
    )
    stdout = "" if result.stdout is None else result.stdout.strip()
    logger.debug("returncode: %s, stdout: %s", result.returncode, stdout)
    return stdout


def git(*args: None | str, check: bool = True, capture_stdout: bool = True) -> str:
    """Run `git *args`, skipping any Nones."""
    return _run("git", args, check=check, capture_stdout=capture_stdout)


def git_rev_parse(rev: str, *, verify: bool = True, abbrev_ref: bool = False) -> str:
    return git(
        "rev-parse", "--verify" if verify else None, "--abbrev-ref" if abbrev_ref else None, rev
    )


def git_fetch(rev: str) -> str:
    """Fetch rev (e.g. branch or a SHA) from the upstream repository and return its SHA."""
    git("fetch", MAIN_REPO, rev)
    return git_rev_parse("FETCH_HEAD")


def github_repo() -> github.Repository.Repository:
    token = os.environ.get(GH_TOKEN_VAR_NAME)
    if not token:
        die(
            f"Failed to find credentials in {GH_TOKEN_VAR_NAME} env var, please set this and try again"
        )

    try:
        gh = github.Github(auth=github.Auth.Token(token))
        user = gh.get_user()
        repo = gh.get_repo(MAIN_REPO_SLUG)
    except Exception as e:
        die(f"Failed to get Github info; is your token valid? {e}")
    else:
        green(f"Operating on Github as: @{user.login}")

    return repo
