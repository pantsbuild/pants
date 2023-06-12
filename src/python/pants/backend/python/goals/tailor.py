# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.python.dependency_inference.module_mapper import module_from_stripped_path
from pants.backend.python.macros.pipenv_requirements import parse_pipenv_requirements
from pants.backend.python.macros.poetry_requirements import PyProjectToml, parse_pyproject_toml
from pants.backend.python.macros.python_requirements import (
    parse_pyproject_toml as parse_pep621_pyproject_toml,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    PexBinary,
    PexEntryPointField,
    PythonSourcesGeneratorTarget,
    PythonTestsGeneratingSourcesField,
    PythonTestsGeneratorTarget,
    PythonTestUtilsGeneratingSourcesField,
    PythonTestUtilsGeneratorTarget,
    ResolvedPexEntryPoint,
    ResolvePexEntryPointRequest,
)
from pants.base.specs import AncestorGlobSpec, RawSpecs
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.core.target_types import ResourceTarget
from pants.engine.fs import DigestContents, FileContent, PathGlobs, Paths
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target, UnexpandedTargets
from pants.engine.unions import UnionRule
from pants.source.filespec import FilespecMatcher
from pants.source.source_root import SourceRootsRequest, SourceRootsResult
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel
from pants.util.requirements import parse_requirements_file

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PutativePythonTargetsRequest(PutativeTargetsRequest):
    pass


def classify_source_files(paths: Iterable[str]) -> dict[type[Target], set[str]]:
    """Returns a dict of target type -> files that belong to targets of that type."""
    tests_filespec_matcher = FilespecMatcher(PythonTestsGeneratingSourcesField.default, ())
    test_utils_filespec_matcher = FilespecMatcher(PythonTestUtilsGeneratingSourcesField.default, ())

    path_to_file_name = {path: os.path.basename(path) for path in paths}
    test_file_names = set(tests_filespec_matcher.matches(list(path_to_file_name.values())))
    test_util_file_names = set(
        test_utils_filespec_matcher.matches(list(path_to_file_name.values()))
    )

    test_files = {
        path for path, file_name in path_to_file_name.items() if file_name in test_file_names
    }
    test_util_files = {
        path for path, file_name in path_to_file_name.items() if file_name in test_util_file_names
    }
    library_files = set(paths) - test_files - test_util_files
    return {
        PythonTestsGeneratorTarget: test_files,
        PythonTestUtilsGeneratorTarget: test_util_files,
        PythonSourcesGeneratorTarget: library_files,
    }


# The order "__main__" == __name__ would also technically work, but is very
# non-idiomatic, so we ignore it.
_entry_point_re = re.compile(rb"^if __name__ +== +['\"]__main__['\"]: *(#.*)?$", re.MULTILINE)


def is_entry_point(content: bytes) -> bool:
    # Identify files that look like entry points.  We use a regex for speed, as it will catch
    # almost all correct cases in practice, with extremely rare false positives (we will only
    # have a false positive if the matching code is in a multiline string indented all the way
    # to the left). Looking at the ast would be more correct, technically, but also more laborious,
    # trickier to implement correctly for different interpreter versions, and much slower.
    return _entry_point_re.search(content) is not None


async def _find_resource_py_typed_targets(
    py_typed_files_globs: PathGlobs, all_owned_sources: AllOwnedSources
) -> list[PutativeTarget]:
    """Find resource targets that may be created after discovering any `py.typed` files."""
    all_py_typed_files = await Get(Paths, PathGlobs, py_typed_files_globs)
    unowned_py_typed_files = set(all_py_typed_files.files) - set(all_owned_sources)

    putative_targets = []
    for dirname, filenames in group_by_dir(unowned_py_typed_files).items():
        putative_targets.append(
            PutativeTarget.for_target_type(
                ResourceTarget,
                kwargs={"source": "py.typed"},
                path=dirname,
                name="py_typed",
                triggering_sources=sorted(filenames),
            )
        )
    return putative_targets


async def _find_source_targets(
    py_files_globs: PathGlobs, all_owned_sources: AllOwnedSources, python_setup: PythonSetup
) -> list[PutativeTarget]:
    result = []
    check_if_init_file_empty: dict[str, tuple[str, str]] = {}  # full_path: (dirname, filename)

    all_py_files = await Get(Paths, PathGlobs, py_files_globs)
    unowned_py_files = set(all_py_files.files) - set(all_owned_sources)
    classified_unowned_py_files = classify_source_files(unowned_py_files)
    for tgt_type, paths in classified_unowned_py_files.items():
        for dirname, filenames in group_by_dir(paths).items():
            name: str | None
            if issubclass(tgt_type, PythonTestsGeneratorTarget):
                name = "tests"
            elif issubclass(tgt_type, PythonTestUtilsGeneratorTarget):
                name = "test_utils"
            else:
                name = None
            if (
                python_setup.tailor_ignore_empty_init_files
                and tgt_type == PythonSourcesGeneratorTarget
                and filenames in ({"__init__.py"}, {"__init__.pyi"})
            ):
                f = next(iter(filenames))
                check_if_init_file_empty[os.path.join(dirname, f)] = (dirname, f)
            else:
                result.append(
                    PutativeTarget.for_target_type(
                        tgt_type, path=dirname, name=name, triggering_sources=sorted(filenames)
                    )
                )

    if check_if_init_file_empty:
        init_contents = await Get(DigestContents, PathGlobs(check_if_init_file_empty.keys()))
        for file_content in init_contents:
            if not file_content.content.strip():
                continue
            d, f = check_if_init_file_empty[file_content.path]
            result.append(
                PutativeTarget.for_target_type(
                    PythonSourcesGeneratorTarget, path=d, name=None, triggering_sources=[f]
                )
            )

    return result


@rule(level=LogLevel.DEBUG, desc="Determine candidate Python targets to create")
async def find_putative_targets(
    req: PutativePythonTargetsRequest,
    all_owned_sources: AllOwnedSources,
    python_setup: PythonSetup,
) -> PutativeTargets:
    pts = []
    all_py_files_globs: PathGlobs = req.path_globs("*.py", "*.pyi")

    if python_setup.tailor_source_targets:
        source_targets = await _find_source_targets(
            all_py_files_globs, all_owned_sources, python_setup
        )
        pts.extend(source_targets)

    if python_setup.tailor_py_typed_targets:
        all_py_typed_files_globs: PathGlobs = req.path_globs("py.typed")
        resource_targets = await _find_resource_py_typed_targets(
            all_py_typed_files_globs, all_owned_sources
        )
        pts.extend(resource_targets)

    if python_setup.tailor_requirements_targets:
        # Find requirements files.
        (
            all_requirements_files,
            all_pipenv_lockfile_files,
            all_pyproject_toml_contents,
        ) = await MultiGet(
            Get(DigestContents, PathGlobs, req.path_globs("*requirements*.txt")),
            Get(DigestContents, PathGlobs, req.path_globs("Pipfile.lock")),
            Get(DigestContents, PathGlobs, req.path_globs("pyproject.toml")),
        )

        def add_req_targets(files: Iterable[FileContent], alias: str, target_name: str) -> None:
            contents = {i.path: i.content for i in files}
            unowned_files = set(contents) - set(all_owned_sources)
            for fp in unowned_files:
                path, name = os.path.split(fp)

                try:
                    validate(fp, contents[fp], alias, target_name)
                except Exception as e:
                    logger.warning(
                        f"An error occurred when validating `{fp}`: {e}.\n\n"
                        "You'll need to create targets for its contents manually.\n"
                        "To silence this error in future, see "
                        "https://www.pantsbuild.org/docs/reference-tailor#section-ignore-paths \n"
                    )
                    continue

                pts.append(
                    PutativeTarget(
                        path=path,
                        name=target_name,
                        type_alias=alias,
                        triggering_sources=[fp],
                        owned_sources=[name],
                        kwargs=(
                            {}
                            if alias != "python_requirements" or name == "requirements.txt"
                            else {"source": name}
                        ),
                    )
                )

        def validate(path: str, contents: bytes, alias: str, target_name: str) -> None:
            if alias == "python_requirements":
                if path.endswith("pyproject.toml"):
                    return validate_pep621_requirements(path, contents)
                return validate_python_requirements(path, contents)
            elif alias == "pipenv_requirements":
                return validate_pipenv_requirements(contents)
            elif alias == "poetry_requirements":
                return validate_poetry_requirements(contents)

        def validate_python_requirements(path: str, contents: bytes) -> None:
            for _ in parse_requirements_file(contents.decode(), rel_path=path):
                pass

        def validate_pep621_requirements(path: str, contents: bytes) -> None:
            list(parse_pep621_pyproject_toml(contents.decode(), rel_path=path))

        def validate_pipenv_requirements(contents: bytes) -> None:
            parse_pipenv_requirements(contents)

        def validate_poetry_requirements(contents: bytes) -> None:
            p = PyProjectToml(PurePath(), PurePath(), contents.decode())
            parse_pyproject_toml(p)

        add_req_targets(all_requirements_files, "python_requirements", "reqs")
        add_req_targets(all_pipenv_lockfile_files, "pipenv_requirements", "pipenv")
        add_req_targets(
            {fc for fc in all_pyproject_toml_contents if b"[tool.poetry" in fc.content},
            "poetry_requirements",
            "poetry",
        )

        def pyproject_toml_has_pep621(fc) -> bool:
            try:
                return (
                    len(list(parse_pep621_pyproject_toml(fc.content.decode(), rel_path=fc.path)))
                    > 0
                )
            except Exception:
                return False

        add_req_targets(
            {fc for fc in all_pyproject_toml_contents if pyproject_toml_has_pep621(fc)},
            "python_requirements",
            "reqs",
        )

    if python_setup.tailor_pex_binary_targets:
        # Find binary targets.

        # Get all files whose content indicates that they are entry points or are __main__.py files.
        digest_contents = await Get(DigestContents, PathGlobs, all_py_files_globs)
        all_main_py = await Get(Paths, PathGlobs, req.path_globs("__main__.py"))
        entry_points = [
            file_content.path
            for file_content in digest_contents
            if is_entry_point(file_content.content)
        ] + list(all_main_py.files)

        # Get the modules for these entry points.
        src_roots = await Get(
            SourceRootsResult, SourceRootsRequest, SourceRootsRequest.for_files(entry_points)
        )
        module_to_entry_point = {}
        for entry_point in entry_points:
            entry_point_path = PurePath(entry_point)
            src_root = src_roots.path_to_root[entry_point_path]
            stripped_entry_point = entry_point_path.relative_to(src_root.path)
            module = module_from_stripped_path(stripped_entry_point)
            module_to_entry_point[module] = entry_point

        # Get existing binary targets for these entry points.
        entry_point_dirs = {os.path.dirname(entry_point) for entry_point in entry_points}
        possible_existing_binary_targets = await Get(
            UnexpandedTargets,
            RawSpecs(
                ancestor_globs=tuple(AncestorGlobSpec(d) for d in entry_point_dirs),
                description_of_origin="the `pex_binary` tailor rule",
            ),
        )
        possible_existing_binary_entry_points = await MultiGet(
            Get(ResolvedPexEntryPoint, ResolvePexEntryPointRequest(t[PexEntryPointField]))
            for t in possible_existing_binary_targets
            if t.has_field(PexEntryPointField)
        )
        possible_existing_entry_point_modules = {
            rep.val.module for rep in possible_existing_binary_entry_points if rep.val
        }
        unowned_entry_point_modules = (
            module_to_entry_point.keys() - possible_existing_entry_point_modules
        )

        # Generate new targets for entry points that don't already have one.
        for entry_point_module in unowned_entry_point_modules:
            entry_point = module_to_entry_point[entry_point_module]
            path, fname = os.path.split(entry_point)
            name = os.path.splitext(fname)[0]
            pts.append(
                PutativeTarget.for_target_type(
                    target_type=PexBinary,
                    path=path,
                    name=name,
                    triggering_sources=tuple(),
                    kwargs={"entry_point": fname},
                )
            )

    return PutativeTargets(pts)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativePythonTargetsRequest),
    ]
