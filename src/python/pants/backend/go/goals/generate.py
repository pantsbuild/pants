# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import re
import shlex
import string
from dataclasses import dataclass
from typing import Mapping

from pants.backend.go.target_types import GoPackageSourcesField
from pants.backend.go.util_rules import first_party_pkg, goroot, sdk
from pants.backend.go.util_rules.build_opts import GoBuildOptions, GoBuildOptionsFromTargetRequest
from pants.backend.go.util_rules.first_party_pkg import (
    FallibleFirstPartyPkgAnalysis,
    FallibleFirstPartyPkgDigest,
    FirstPartyPkgAnalysis,
    FirstPartyPkgAnalysisRequest,
    FirstPartyPkgDigestRequest,
)
from pants.backend.go.util_rules.goroot import GoRoot
from pants.build_graph.address import Address
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import (
    CreateDigest,
    DigestContents,
    DigestEntries,
    FileEntry,
    SnapshotDiff,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.native_engine import (
    EMPTY_DIGEST,
    AddPrefix,
    Digest,
    MergeDigests,
    Snapshot,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import Targets
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.dirutil import group_by_dir
from pants.util.strutil import help_text, softwrap

# Adapted from Go toolchain.
# See https://github.com/golang/go/blob/master/src/cmd/go/internal/generate/generate.go and
# https://github.com/golang/go/blob/cc1b20e8adf83865a1dbffa259c7a04ef0699b43/src/os/env.go#L16-L96
#
# Original copyright:
#   // Copyright 2011 The Go Authors. All rights reserved.
#   // Use of this source code is governed by a BSD-style
#   // license that can be found in the LICENSE file.


_GENERATE_DIRECTIVE_RE = re.compile(rb"^//go:generate[ \t](.*)$")


class GoGenerateGoalSubsystem(GoalSubsystem):
    name = "go-generate"
    help = help_text(
        """
        Run each command in a package described by a `//go:generate` directive. This is equivalent to running
        `go generate` on a Go package.

        Note: Just like with `go generate`, the `go-generate` goal is never run as part of the build and
        must be run manually to invoke the commands described by the `//go:generate` directives.

        See https://go.dev/blog/generate for details.
        """
    )

    class EnvironmentAware(Subsystem.EnvironmentAware):
        env_vars = StrListOption(
            default=["LANG", "LC_CTYPE", "LC_ALL", "PATH"],
            help=softwrap(
                """
                Environment variables to set when invoking generator programs.
                Entries are either strings in the form `ENV_VAR=value` to set an explicit value;
                or just `ENV_VAR` to copy the value from Pants's own environment.
                """
            ),
            advanced=True,
        )


class GoGenerateGoal(Goal):
    subsystem_cls = GoGenerateGoalSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY  # TODO(#17129) — Migrate this.


@dataclass(frozen=True)
class RunPackageGeneratorsRequest:
    address: Address
    regex: str | None = None


@dataclass(frozen=True)
class RunPackageGeneratorsResult:
    digest: Digest


_SHELL_SPECIAL_VAR = frozenset(
    ["*", "#", "$", "@", "!", "?", "-", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
)
_ALPHANUMERIC = frozenset([*string.ascii_letters, *string.digits, "_"])


def _get_shell_name(s: str) -> tuple[str, int]:
    if s[0] == "{":
        if len(s) > 2 and s[1] in _SHELL_SPECIAL_VAR and s[2] == "}":
            return s[1:2], 3
        for i in range(1, len(s)):
            if s[i] == "}":
                if i == 1:
                    return "", 2  # Bad syntax; eat "${}"
                return s[1:i], i + 1
        return "", 1  # Bad syntax; eat "${"
    elif s[0] in _SHELL_SPECIAL_VAR:
        return s[0:1], 1

    i = 0
    while i < len(s) and s[i] in _ALPHANUMERIC:
        i += 1

    return s[:i], i


def _expand_env(s: str, m: Mapping[str, str]) -> str:
    i = 0
    buf: str | None = None
    j = 0
    while j < len(s):
        if s[j] == "$" and j + 1 < len(s):
            if buf is None:
                buf = ""
            buf += s[i:j]
            name, w = _get_shell_name(s[j + 1 :])
            if name == "" and w > 0:
                # Encountered invalid syntax; eat the characters.
                pass
            elif name == "":
                # Valid syntax, but $ was not followed by a name. Leave the dollar character untouched.
                buf += s[j]
            else:
                buf += m.get(name, "")
            j += w
            i = j + 1
        j += 1

    if buf is None:
        return s
    return buf + s[i:]


async def _run_generators(
    analysis: FirstPartyPkgAnalysis,
    digest: Digest,
    dir_path: str,
    go_file: str,
    goroot: GoRoot,
    base_env: Mapping[str, str],
) -> Digest:
    digest = await Get(Digest, MergeDigests([digest]))
    digest_contents = await Get(DigestContents, Digest, digest)
    content: bytes | None = None
    for entry in digest_contents:
        if entry.path == os.path.join(dir_path, go_file):
            content = entry.content
            break

    if content is None:
        raise ValueError("Illegal state: Unable to extract Go file from digest.")

    cmd_shorthand: dict[str, tuple[str, ...]] = {}

    for line_num, line in enumerate(content.splitlines(), start=1):
        m = _GENERATE_DIRECTIVE_RE.fullmatch(line)
        if not m:
            continue

        # Extract the command to run.
        # Note: Go only processes double-quoted strings. Thus, using shlex.split is actually more liberal than
        # Go because it also allows single-quoted strings.
        args = shlex.split(m.group(1).decode())

        # Store any command shorthands for later use.
        if args[0] == "-command":
            if len(args) <= 1:
                raise ValueError(
                    f"{go_file}:{line_num}: -command syntax used but no command name specified"
                )
            cmd_shorthand[args[1]] = tuple(args[2:])
            continue

        # Replace any shorthand command with the previously-stored arguments.
        if args[0] in cmd_shorthand:
            args = [*cmd_shorthand[args[0]], *args[1:]]

        # If the program calls for `go`, then use the full path to the `go` binary in the GOROOT.
        if args[0] == "go":
            args[0] = os.path.join(goroot.path, "bin", "go")

        env = {
            "GOOS": goroot.goos,
            "GOARCH": goroot.goarch,
            "GOFILE": go_file,
            "GOLINE": str(line_num),
            "GOPACKAGE": analysis.name,
            "GOROOT": goroot.path,
            "DOLLAR": "$",
            **base_env,
        }

        for i, arg in enumerate(args):
            args[i] = _expand_env(arg, env)

        # Invoke the subprocess and store its output for use as input root of next command (if any).
        result = await Get(  # noqa: PNT30: this is inherently sequential
            ProcessResult,
            Process(
                argv=args,
                input_digest=digest,
                working_directory=dir_path,
                output_directories=[".", "!.goroot"],
                env=env,
                description=f"Process `go generate` directives in file: {os.path.join(dir_path, go_file)}",
                immutable_input_digests={".goroot": goroot.digest},
            ),
        )
        digest = await Get(  # noqa: PNT30: this is inherently sequential
            Digest, AddPrefix(result.output_digest, dir_path)
        )

    return digest


@dataclass(frozen=True)
class OverwriteMergeDigests:
    orig_digest: Digest
    new_digest: Digest


@rule
async def merge_digests_with_overwrite(request: OverwriteMergeDigests) -> Digest:
    orig_snapshot, new_snapshot, orig_digest_entries, new_digest_entries = await MultiGet(
        Get(Snapshot, Digest, request.orig_digest),
        Get(Snapshot, Digest, request.new_digest),
        Get(DigestEntries, Digest, request.orig_digest),
        Get(DigestEntries, Digest, request.new_digest),
    )

    orig_snapshot_grouped = group_by_dir(orig_snapshot.files)
    new_snapshot_grouped = group_by_dir(new_snapshot.files)

    diff = SnapshotDiff.from_snapshots(orig_snapshot, new_snapshot)

    output_entries: list[FileEntry] = []

    # Keep unchanged original files and directories in the output.
    orig_files_to_keep = set(diff.our_unique_files)
    for dir_path in diff.our_unique_dirs:
        for filename in orig_snapshot_grouped[dir_path]:
            orig_files_to_keep.add(os.path.join(dir_path, filename))
    for entry in orig_digest_entries:
        if isinstance(entry, FileEntry) and entry.path in orig_files_to_keep:
            output_entries.append(entry)

    # Add new files/directories and changed files to the output.
    new_files_to_keep = {*diff.their_unique_files, *diff.changed_files}
    for dir_path in diff.their_unique_dirs:
        for filename in new_snapshot_grouped[dir_path]:
            new_files_to_keep.add(os.path.join(dir_path, filename))
    for entry in new_digest_entries:
        if isinstance(entry, FileEntry) and entry.path in new_files_to_keep:
            output_entries.append(entry)

    digest = await Get(Digest, CreateDigest(output_entries))
    return digest


@rule
async def run_go_package_generators(
    request: RunPackageGeneratorsRequest,
    goroot: GoRoot,
    subsystem: GoGenerateGoalSubsystem.EnvironmentAware,
) -> RunPackageGeneratorsResult:
    build_opts = await Get(GoBuildOptions, GoBuildOptionsFromTargetRequest(request.address))
    fallible_analysis, env = await MultiGet(
        Get(
            FallibleFirstPartyPkgAnalysis,
            FirstPartyPkgAnalysisRequest(
                request.address, build_opts=build_opts, extra_build_tags=("generate",)
            ),
        ),
        Get(EnvironmentVars, EnvironmentVarsRequest(subsystem.env_vars)),
    )
    if not fallible_analysis.analysis:
        raise ValueError(f"Analysis failure for {request.address}: {fallible_analysis.stderr}")
    analysis = fallible_analysis.analysis
    dir_path = analysis.dir_path if analysis.dir_path else "."

    fallible_pkg_digest = await Get(
        FallibleFirstPartyPkgDigest,
        FirstPartyPkgDigestRequest(request.address, build_opts=build_opts),
    )
    if fallible_pkg_digest.pkg_digest is None:
        raise ValueError(
            f"Unable to obtain digest for {request.address}: {fallible_pkg_digest.stderr}"
        )
    pkg_digest = fallible_pkg_digest.pkg_digest

    # Scan each Go file in the package for generate directives. Process them sequentially so that an error in
    # an earlier-processed file prevents later files from being processed.
    output_digest = EMPTY_DIGEST
    for go_file in analysis.go_files:
        output_digest_for_go_file = await _run_generators(
            analysis, pkg_digest.digest, dir_path, go_file, goroot, env
        )
        output_digest = await Get(  # noqa: PNT30: requires triage
            Digest, OverwriteMergeDigests(output_digest, output_digest_for_go_file)
        )

    return RunPackageGeneratorsResult(output_digest)


@goal_rule
async def go_generate(targets: Targets, workspace: Workspace) -> GoGenerateGoal:
    go_package_targets = [tgt for tgt in targets if tgt.has_field(GoPackageSourcesField)]
    results = await MultiGet(
        Get(RunPackageGeneratorsResult, RunPackageGeneratorsRequest(tgt.address))
        for tgt in go_package_targets
    )
    output_digest = await Get(Digest, MergeDigests([r.digest for r in results]))
    workspace.write_digest(output_digest)
    return GoGenerateGoal(exit_code=0)


def rules():
    return (
        *collect_rules(),
        *first_party_pkg.rules(),
        *goroot.rules(),
        *sdk.rules(),
    )
