# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.dependency_inference.rules import PythonInference
from pants.backend.python.rules.ancestor_files import AncestorFiles, AncestorFilesRequest
from pants.engine.fs import Digest, DigestContents, Snapshot
from pants.engine.rules import Get, collect_rules, rule


@dataclass(frozen=True)
class MissingInitRequest:
    snapshot: Snapshot
    sources_stripped: bool  # True iff snapshot has already had source roots stripped.


@dataclass(frozen=True)
class MissingInit:
    """Any missing empty __init__.py files found."""

    snapshot: Snapshot


class MissingNonEmptyInitFiles(Exception):
    pass


@rule
async def find_missing_empty_init_files(
    request: MissingInitRequest, python_inference: PythonInference,
) -> MissingInit:
    """Find missing empty __init__.py files.

    This is a convenience hack, so that repos that aren't using dep inference don't have
    to create explicit dependencies on empty ancestor __init__.py files everywhere just
    so their imports work.

    NB We only apply this convenience if those __init__.py files are empty. If an __init__.py
    contains code then that code might have dependencies, and you must bring them in via
    a dependency (explicit or inferred). This is a compromise that reflects the dual role
    of __init__.py as both "a sentinel file required for imports to work" and "a regular source
    file that contains code".
    """
    extra_init_files = await Get(
        AncestorFiles,
        AncestorFilesRequest("__init__.py", request.snapshot, request.sources_stripped),
    )
    extra_init_files_contents = await Get(DigestContents, Digest, extra_init_files.snapshot.digest)
    non_empty = [fc.path for fc in extra_init_files_contents if fc.content]
    if non_empty:
        inference_hint = (
            ""
            if python_inference.inits
            else (
                ", and then add explicit dependencies (or enable `--python-infer-inits` to "
                "automatically add the dependencies)"
            )
        )
        err_msg = (
            f"Missing dependencies on non-empty __init__.py files: {','.join(non_empty)}. "
            f"To fix: ensure that targets own each of these files{inference_hint}."
        )
        # TODO: Note that in the stripped case these paths will be missing their source roots,
        #  which makes this error message slightly less useful to the end user.
        #  Once we overhaul the whole stripped vs. non-stripped confusion, this should be remedied.
        raise MissingNonEmptyInitFiles(err_msg)

    return MissingInit(extra_init_files.snapshot)


def rules():
    return collect_rules()
