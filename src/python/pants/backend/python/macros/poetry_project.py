# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from typing import Any, Optional

import packaging.version
import toml
from pkg_resources import Requirement


def get_max_caret(proj_name: str, version: str) -> str:
    major = "0"
    minor = "0"
    micro = "0"

    try:
        parsed_version = packaging.version.Version(version)
        if parsed_version.major != 0:
            major = str(parsed_version.major + 1)
        elif parsed_version.minor != 0:
            minor = str(parsed_version.minor + 1)
        elif parsed_version.micro != 0:
            micro = str(parsed_version.micro + 1)
        else:
            base_len = len(parsed_version.base_version.split("."))
            if base_len >= 3:
                micro = "1"
            elif base_len == 2:
                minor = "1"
            elif base_len == 1:
                major = "1"
    except packaging.version.InvalidVersion:
        print(
            f"Warning: version {version} for {proj_name} is not PEP440-compliant; this requirement"
            f" will be left as >={version},<{version}"
        )
        return version
    return f"{major}.{minor}.{micro}"


def get_max_tilde(proj_name: str, version: str) -> str:
    major = "0"
    minor = "0"
    micro = "0"
    try:
        parsed_version = packaging.version.Version(version)
        base_len = len(parsed_version.base_version.split("."))
        if base_len >= 2:
            minor = str(parsed_version.minor + 1)
            major = str(parsed_version.major)
        elif base_len == 1:
            major = str(parsed_version.major + 1)

    except packaging.version.InvalidVersion:
        print(
            f"Warning: version {version} for {proj_name} is not PEP440-compliant; this requirement"
            f" will be parsed as >={version},<{version}"
        )
        return version
    return f"{major}.{minor}.{micro}"


def handle_str_attr(proj_name: str, attributes: str) -> str:
    valid_specifiers = "<>!~="
    pep440_reqs = []
    comma_split_reqs = [i.strip() for i in attributes.split(",")]
    for req in comma_split_reqs:
        if req[0] == "^":
            max_ver = get_max_caret(proj_name, req[1:])
            min_ver = req[1:]
            pep440_reqs.append(f">={min_ver},<{max_ver}")
        # ~= is an acceptable default operator; however, ~ is not, and IS NOT the same as ~=
        elif req[0] == "~" and req[1] != "=":
            max_ver = get_max_tilde(proj_name, req[1:])
            min_ver = req[1:]
            pep440_reqs.append(f">={min_ver},<{max_ver}")
        else:
            if req[0] not in valid_specifiers:
                pep440_reqs.append(f"=={req}")
            else:
                pep440_reqs.append(req)
    return f"{proj_name} {','.join(pep440_reqs)}"


def parse_python_constraint(constr: str | None) -> str:
    if constr is None:
        return ""
    valid_specifiers = "<>!~= "
    or_and_split = [[j.strip() for j in i.split(",")] for i in constr.split("||")]
    ver_parsed = [[handle_str_attr("", j) for j in i] for i in or_and_split]

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


def handle_dict_attr(proj_name: str, attributes: dict[str, str]) -> str:
    def produce_match(sep: str, feat: Optional[str]) -> str:
        return f"{sep}{feat}" if feat else ""

    git_lookup = attributes.get("git")
    if git_lookup is not None:
        # Making revision optional and supporting a branch are not
        # strictly in agreement with PEP440 (does not comment on
        # specifying a branch). However, pip seems to accept it fine
        # (see pypa/pip issue 7650)
        # so I can't see a reason not to support it here...?

        rev_lookup = produce_match("#", attributes.get("rev"))
        branch_lookup = produce_match("@", attributes.get("branch"))
        tag_lookup = produce_match("@", attributes.get("tag"))

        return f"{proj_name} @ git+{git_lookup}{tag_lookup}{branch_lookup}{rev_lookup}"

    version_lookup = attributes.get("version")
    path_lookup = attributes.get("path")
    if path_lookup is not None:
        return f"{proj_name} @ file://{path_lookup}"
    url_lookup = attributes.get("url")
    if url_lookup is not None:
        return f"{proj_name} @ {url_lookup}"
    if version_lookup is not None:
        markers_lookup = produce_match(";", attributes.get("markers"))
        python_lookup = parse_python_constraint(attributes.get("python"))
        version_parsed = handle_str_attr(proj_name, version_lookup)
        return (
            f"{version_parsed}"
            f"{markers_lookup}"
            f"{' and ' if python_lookup and markers_lookup else (';' if python_lookup else '')}"
            f"{python_lookup}"
        )
    else:
        # This case should never happen if input is formed correctly; this
        # ultimately will cause the Requirement.parse call to fail.
        # TODO: add appropriate error handling
        return ""


def parse_single_dependency(
    proj_name: str, attributes: str | dict[str, Any] | list[dict[str, Any]]
) -> tuple[Requirement, ...]:
    if isinstance(attributes, str):
        return (Requirement.parse(handle_str_attr(proj_name, attributes)),)
    elif isinstance(attributes, dict):
        return (Requirement.parse(handle_dict_attr(proj_name, attributes)),)
    elif isinstance(attributes, list):
        return tuple([Requirement.parse(handle_dict_attr(proj_name, attr)) for attr in attributes])
    else:
        # Similarly, this is currently added just for mypy checks. Error
        # handling needs to be written to address this properly.
        return (Requirement.parse(""),)


def parse_pyproject_toml(toml_contents: str) -> set[Requirement]:
    parsed = toml.loads(toml_contents)
    poetry_vals = parsed["tool"]["poetry"]
    try:
        dependencies = poetry_vals["dependencies"]
        dev_dependencies = poetry_vals["dev-dependencies"]
    except KeyError:
        print(
            "Missing required `poetry.tools.dependencies` and/or `poetry.tools.dev-dependencies`"
            "fields...perhaps you specified the wrong file?"
            "These can be empty if, for example, you have no dev-dependencies."
        )
        return set()

    all_req_raw = {**dependencies, **dev_dependencies}

    # This cannot be a comprehension, as the special case where one dependency
    # needs to be treated as two dependencies (e.g. version requirement
    # different depending on environment markers) can return two Requirement
    # objects, and comprehensions do not permit asterisk unpacking.
    all_process_deps = set()
    for proj, attr in all_req_raw.items():
        processed_deps = parse_single_dependency(proj, attr)
        for dep in processed_deps:
            all_process_deps.add(dep)
    return all_process_deps
