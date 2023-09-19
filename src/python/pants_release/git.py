# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import shlex
import subprocess

import github
from pants_release.common import die

from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)

MAIN_REPO_SLUG = "pantsbuild/pants"
MAIN_REPO = f"https://github.com/{MAIN_REPO_SLUG}"


def _run(
    exe: str,
    args: tuple[None | str, ...],
    check: bool,
    capture_stdout: bool,
    log_stdout: bool = True,
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
    logger.debug(
        "returncode: %s, stdout: %s", result.returncode, stdout if log_stdout else "<redacted>"
    )
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
    # Borrow the token from `gh`, because it works well both interactively (running `gh auth login`
    # is far more convenient for interactive use than manually generating a token) and in
    # scripts/automation (it reads the `GH_TOKEN=...` env var, if set)
    token = _run("gh", ("auth", "token"), check=False, capture_stdout=True, log_stdout=False)
    if not token:
        die(
            softwrap(
                """
                Failed to find credentials via `gh auth token`; is https://cli.github.com installed
                and authenticated? Auth with `gh auth login` or by setting `GH_TOKEN=...` env var.
                """
            )
        )

    try:
        gh = github.Github(auth=github.Auth.Token(token))
        repo = gh.get_repo(MAIN_REPO_SLUG)
    except Exception as e:
        die(f"Failed to get Github info; is your token valid? {e}")

    return repo
