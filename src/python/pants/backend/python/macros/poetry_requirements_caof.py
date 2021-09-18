# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
import os
import urllib.parse
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Iterable, Iterator, Mapping, Sequence, cast

import toml
from packaging.utils import canonicalize_name as canonicalize_project_name
from packaging.version import InvalidVersion, Version
from typing_extensions import TypedDict

from pants.backend.python.macros.caof_utils import (
    OVERRIDES_TYPE,
    flatten_overrides_to_dependency_field,
)
from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.target_types import normalize_module_mapping
from pants.base.parse_context import ParseContext

logger = logging.getLogger(__name__)


class PyprojectAttr(TypedDict, total=False):
    extras: list[str]
    git: str
    rev: str
    branch: str
    python: str
    markers: str
    tag: str
    version: str
    url: str
    path: str


def get_max_caret(parsed_version: Version) -> str:
    major = 0
    minor = 0
    micro = 0

    if parsed_version.major != 0:
        major = parsed_version.major + 1
    elif parsed_version.minor != 0:
        minor = parsed_version.minor + 1
    elif parsed_version.micro != 0:
        micro = parsed_version.micro + 1
    else:
        base_len = len(parsed_version.base_version.split("."))
        if base_len >= 3:
            micro = 1
        elif base_len == 2:
            minor = 1
        elif base_len == 1:
            major = 1

    return f"{major}.{minor}.{micro}"


def get_max_tilde(parsed_version: Version) -> str:
    major = 0
    minor = 0
    base_len = len(parsed_version.base_version.split("."))
    if base_len >= 2:
        minor = int(str(parsed_version.minor)) + 1
        major = int(str(parsed_version.major))
    elif base_len == 1:
        major = int(str(parsed_version.major)) + 1

    return f"{major}.{minor}.0"


def parse_str_version(attributes: str, **kwargs: str) -> str:
    valid_specifiers = "<>!~="
    pep440_reqs = []
    proj_name = kwargs["proj_name"]
    fp = kwargs["file_path"]
    extras_str = kwargs["extras_str"]
    comma_split_reqs = (i.strip() for i in attributes.split(","))
    for req in comma_split_reqs:
        is_caret = req[0] == "^"
        # ~= is an acceptable default operator; however, ~ is not, and IS NOT the same as ~=
        is_tilde = req[0] == "~" and req[1] != "="
        if is_caret or is_tilde:
            try:
                parsed_version = Version(req[1:])
            except InvalidVersion:
                raise InvalidVersion(
                    f'Failed to parse requirement {proj_name} = "{req}" in {fp} loaded by the '
                    "poetry_requirements macro.\n\nIf you believe this requirement is valid, "
                    "consider opening an issue at https://github.com/pantsbuild/pants/issues so "
                    "that we can update Pants' Poetry macro to support this."
                )

            max_ver = get_max_caret(parsed_version) if is_caret else get_max_tilde(parsed_version)
            min_ver = f"{parsed_version.public}"
            pep440_reqs.append(f">={min_ver},<{max_ver}")
        else:
            pep440_reqs.append(req if req[0] in valid_specifiers else f"=={req}")
    return f"{proj_name}{extras_str} {','.join(pep440_reqs)}"


def parse_python_constraint(constr: str | None, fp: str) -> str:
    if constr is None:
        return ""
    valid_specifiers = "<>!~= "
    # If the user passes multiple Python constraints, they're separated by
    # either '||' signifying a logical 'or', or a comma signifying a logical
    # 'and'. Hence, or_and_split is a 2D list where each inner list is a set of and-ed
    # requirements; every list in the second layer is then or-ed together.
    or_and_split = [[j.strip() for j in i.split(",")] for i in constr.split("||")]

    # We only use parse_str_version to address the version parsing; we don't
    # care about having an actual Requirement object so things like the project name
    # and extras that would ordinarily exist for a project with a string version are left blank here.
    ver_parsed = [
        [parse_str_version(j, proj_name="", file_path=fp, extras_str="") for j in i]
        for i in or_and_split
    ]

    def conv_and(lst: list[str]) -> list:
        return list(itertools.chain(*[i.split(",") for i in lst]))

    def prepend(version: str) -> str:
        return (
            f"python_version{''.join(i for i in version if i in valid_specifiers)} '"
            f"{''.join(i for i in version if i not in valid_specifiers)}'"
        )

    prepend_and_clean = [
        [prepend(".".join(j.split(".")[:2])) for j in conv_and(i)] for i in ver_parsed
    ]
    return (
        f"{'(' if len(or_and_split) > 1 else ''}"
        f"{') or ('.join([' and '.join(i) for i in prepend_and_clean])}"
        f"{')' if len(or_and_split) > 1 else ''}"
    )


@dataclass(frozen=True)
class PyProjectToml:
    build_root: PurePath
    toml_relpath: PurePath
    toml_contents: str

    @classmethod
    def create(cls, parse_context: ParseContext, pyproject_toml_relpath: str) -> PyProjectToml:
        build_root = Path(parse_context.build_root)
        toml_relpath = PurePath(parse_context.rel_path, pyproject_toml_relpath)
        return cls(
            build_root=build_root,
            toml_relpath=toml_relpath,
            toml_contents=(build_root / toml_relpath).read_text(),
        )

    def parse(self) -> Mapping[str, Any]:
        return toml.loads(self.toml_contents)

    def _non_pants_project_abs_path(self, path: Path) -> Path | None:
        resolved = path.resolve()
        if resolved.is_file():
            return resolved

        try:
            resolved.relative_to(self.build_root)
        except ValueError:
            return resolved

        return None

    def non_pants_project_abs_path(self, path: str) -> Path | None:
        """Determine if the given path represents a non-Pants controlled project.

        If the path points to a file, it's assumed the file is a distribution ( a wheel or sdist)
        and the absolute path of that file is returned.

        If the path points to a directory and that directory is outside of the build root, it's
        assumed the directory is the root of a buildable Python project (i.e.: it contains a
        pyproject.toml or setup.py) and the absolute path of the project is returned.

        Otherwise, `None` is returned since the directory lies inside the build root and is assumed
        to be a Pants controlled project.
        """
        # TODO(John Sirois): This leaves the case where the path is a Python project directory
        #  inside the build root that the user actually wants Pex / Pip to build. A concrete case
        #  for this would be a repo where third party is partially handled with vendored exploded
        #  source distributions. If someone in the wild needs the described case, plumb a
        #  PoetryRequirements parameter that can list paths to treat as Pants controlled or
        #  vice-versa.
        given_path = Path(path)
        if given_path.is_absolute():
            return self._non_pants_project_abs_path(given_path)
        else:
            return self._non_pants_project_abs_path(
                Path(self.build_root / self.toml_relpath).parent / given_path
            )


def produce_match(sep: str, feat: Any) -> str:
    return f"{sep}{feat}" if feat else ""


def add_markers(base: str, attributes: PyprojectAttr, fp) -> str:
    markers_lookup = produce_match("", attributes.get("markers"))
    python_lookup = parse_python_constraint(attributes.get("python"), fp)

    # Python constraints are passed as a `python_version` environment marker; if we have multiple
    # markers, we evaluate them as one whole, and then AND with the new marker for the Python constraint.
    # E.g. (marker1 AND marker2 OR marker3...) AND (python_version)
    # rather than (marker1 AND marker2 OR marker3 AND python_version)
    if not markers_lookup and not python_lookup:
        return base

    result = f"{base};("

    if markers_lookup:
        result += f"{markers_lookup})"
    if python_lookup and markers_lookup:
        result += " and ("
    if python_lookup:
        result += f"{python_lookup})"

    return result


def handle_dict_attr(
    proj_name: str, attributes: PyprojectAttr, pyproject_toml: PyProjectToml
) -> str | None:
    base = ""
    fp = str(pyproject_toml.toml_relpath)

    extras_lookup = attributes.get("extras")
    if isinstance(extras_lookup, list):
        extras_str = f"[{','.join(extras_lookup)}]"
    else:
        extras_str = ""

    git_lookup = attributes.get("git")
    if git_lookup is not None:
        # If no URL scheme (e.g., `{git = "git@github.com:foo/bar.git"}`) we assume ssh,
        # i.e., we convert to git+ssh://git@github.com/foo/bar.git.
        if not urllib.parse.urlsplit(git_lookup).scheme:
            git_lookup = f"ssh://{git_lookup.replace(':', '/', 1)}"
        rev_lookup = produce_match("#", attributes.get("rev"))
        branch_lookup = produce_match("@", attributes.get("branch"))
        tag_lookup = produce_match("@", attributes.get("tag"))

        base = f"{proj_name}{extras_str} @ git+{git_lookup}{tag_lookup}{branch_lookup}{rev_lookup}"

    path_lookup = attributes.get("path")
    if path_lookup is not None:
        non_pants_project_abs_path = pyproject_toml.non_pants_project_abs_path(path_lookup)
        if non_pants_project_abs_path:
            base = f"{proj_name}{extras_str} @ file://{non_pants_project_abs_path}"
        else:
            # An internal path will be handled by normal Pants dependencies and dependency inference;
            # i.e.: it never represents a third party requirement.
            return None

    url_lookup = attributes.get("url")
    if url_lookup is not None:
        base = f"{proj_name}{extras_str} @ {url_lookup}"

    version_lookup = attributes.get("version")
    if version_lookup is not None:
        base = parse_str_version(
            version_lookup, file_path=fp, extras_str=extras_str, proj_name=proj_name
        )

    if len(base) == 0:
        raise ValueError(
            f"{proj_name} is not formatted correctly; at minimum provide either a version, url, path "
            "or git location for your dependency. "
        )

    return add_markers(base, attributes, fp)


def parse_single_dependency(
    proj_name: str,
    attributes: str | Mapping[str, str | Sequence] | Sequence[Mapping[str, str | Sequence]],
    pyproject_toml: PyProjectToml,
) -> Iterator[PipRequirement]:

    if isinstance(attributes, str):
        # E.g. `foo = "~1.1~'.
        yield PipRequirement.parse(
            parse_str_version(
                attributes,
                proj_name=proj_name,
                file_path=str(pyproject_toml.toml_relpath),
                extras_str="",
            )
        )
    elif isinstance(attributes, dict):
        # E.g. `foo = {version = "~1.1"}`.
        pyproject_attr = cast(PyprojectAttr, attributes)
        req_str = handle_dict_attr(proj_name, pyproject_attr, pyproject_toml)
        if req_str:
            yield PipRequirement.parse(req_str)
    elif isinstance(attributes, list):
        # E.g. ` foo = [{version = "1.1","python" = "2.7"}, {version = "1.1","python" = "2.7"}]
        for attr in attributes:
            req_str = handle_dict_attr(proj_name, attr, pyproject_toml)
            if req_str:
                yield PipRequirement.parse(req_str)
    else:
        raise AssertionError(
            "Error: invalid Poetry requirement format. Expected type of requirement attributes to "
            f"be string, dict, or list, but was of type {type(attributes).__name__}."
        )


def parse_pyproject_toml(pyproject_toml: PyProjectToml) -> set[PipRequirement]:
    parsed = pyproject_toml.parse()
    try:
        poetry_vals = parsed["tool"]["poetry"]
    except KeyError:
        raise KeyError(
            f"No section `tool.poetry` found in {pyproject_toml.toml_relpath}, which "
            "is loaded by Pants from a `poetry_requirements` macro. "
            "Did you mean to set up Poetry?"
        )
    dependencies = poetry_vals.get("dependencies", {})
    # N.B.: The "python" dependency is a special dependency required by Poetry that only serves to
    # constraint the python interpreter versions the project works with; so we skip that.
    # See: https://python-poetry.org/docs/pyproject/#dependencies-and-dev-dependencies
    dependencies.pop("python", None)

    groups = poetry_vals.get("group", {})
    group_deps: dict[str, PyprojectAttr] = {}

    for group in groups.values():
        group_deps.update(group.get("dependencies", {}))

    dev_dependencies = poetry_vals.get("dev-dependencies", {})
    if not dependencies and not dev_dependencies and not group_deps:
        logger.warning(
            "No requirements defined in any Poetry dependency groups, tool.poetry.dependencies and "
            f"tool.poetry.dev-dependencies in {pyproject_toml.toml_relpath}, which is loaded "
            "by Pants from a poetry_requirements macro. Did you mean to populate these "
            "with requirements?"
        )

    return set(
        itertools.chain.from_iterable(
            parse_single_dependency(proj, attr, pyproject_toml)
            for proj, attr in {**dependencies, **dev_dependencies, **group_deps}.items()
        )
    )


class PoetryRequirementsCAOF:
    """Translates dependencies specified in a  pyproject.toml Poetry file to a set of
    "python_requirements_library" targets.

    For example, if pyproject.toml contains the following entries under
    poetry.tool.dependencies: `foo = ">1"` and `bar = ">2.4"`,

        python_requirement(
          name="foo",
          requirements=["foo>1"],
        )

        python_requirement(
          name="bar",
          requirements=["bar>2.4"],
        )

    See Poetry documentation for correct specification of pyproject.toml:
    https://python-poetry.org/docs/pyproject/

    You may also use the parameter `module_mapping` to teach Pants what modules each of your
    requirements provide. For any requirement unspecified, Pants will default to the name of the
    requirement. This setting is important for Pants to know how to convert your import
    statements back into your dependencies. For example:

        poetry_requirements(
          module_mapping={
            "ansicolors": ["colors"],
            "setuptools": ["pkg_resources"],
          }
        )
    """

    def __init__(self, parse_context):
        self._parse_context = parse_context

    def __call__(
        self,
        *,
        source: str = "pyproject.toml",
        module_mapping: Mapping[str, Iterable[str]] | None = None,
        type_stubs_module_mapping: Mapping[str, Iterable[str]] | None = None,
        overrides: OVERRIDES_TYPE = None,
    ) -> None:
        """
        :param module_mapping: a mapping of requirement names to a list of the modules they provide.
            For example, `{"ansicolors": ["colors"]}`. Any unspecified requirements will use the
            requirement name as the default module, e.g. "Django" will default to
            `modules=["django"]`.
        """
        req_file_tgt = self._parse_context.create_object(
            "_python_requirements_file",
            name=source.replace(os.path.sep, "_"),
            sources=[source],
        )
        requirements_dep = f":{req_file_tgt.name}"

        normalized_module_mapping = normalize_module_mapping(module_mapping)
        normalized_type_stubs_module_mapping = normalize_module_mapping(type_stubs_module_mapping)

        dependencies_overrides = flatten_overrides_to_dependency_field(
            overrides, macro_name="python_requirements", build_file_dir=self._parse_context.rel_path
        )

        requirements = parse_pyproject_toml(PyProjectToml.create(self._parse_context, source))
        for parsed_req in requirements:
            normalized_proj_name = canonicalize_project_name(parsed_req.project_name)
            self._parse_context.create_object(
                "python_requirement",
                name=parsed_req.project_name,
                requirements=[parsed_req],
                modules=normalized_module_mapping.get(normalized_proj_name),
                type_stub_modules=normalized_type_stubs_module_mapping.get(normalized_proj_name),
                dependencies=[
                    requirements_dep,
                    *dependencies_overrides.get(normalized_proj_name, []),
                ],
            )
