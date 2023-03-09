#!/usr/bin/env python3
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""A script to replace deprecated uses of `globs`, `rglobs`, and `zglobs` in BUILD files with a
direct list of files and globs.

Run `python3 fix_deprecated_globs_usage.py --help`.
"""

import argparse
import ast
import itertools
import logging
import os.path
import re
from difflib import unified_diff
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set, Union


def main() -> None:
    args = create_parser().parse_args()
    build_files: Set[Path] = {
        fp
        for folder in args.folders
        for fp in [*folder.rglob("BUILD"), *folder.rglob("BUILD.*")]
        # Check that it really is a BUILD file
        if fp.is_file() and fp.stem == "BUILD"
    }
    updates: Dict[Path, List[str]] = {}
    for build in build_files:
        try:
            possibly_new_build = generate_possibly_new_build(build)
        except Exception:
            logging.warning(f"Could not parse the BUILD file {build}. Skipping.")
            continue
        if possibly_new_build is not None:
            updates[build] = possibly_new_build
    for build, new_content in updates.items():
        if args.preview:
            print(generate_diff(build, new_content))
        else:
            build.write_text("\n".join(new_content) + "\n")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Modernize BUILD files to no longer use globs, rglobs, and zglobs.",
    )
    parser.add_argument(
        "folders", type=Path, nargs="+", help="Folders to recursively search for `BUILD` files"
    )
    parser.add_argument(
        "-p",
        "--preview",
        action="store_true",
        help="Output to stdout rather than overwriting BUILD files.",
    )
    return parser


class GlobType(Enum):
    globs = "globs"
    rglobs = "rglobs"
    zglobs = "zglobs"


class GlobFunction(NamedTuple):
    glob_type: GlobType
    includes: List[str]
    excludes: Optional[List[str]]

    @staticmethod
    def normalize_rglob(rglob: str) -> str:
        """We must expand rglobs for them to work properly.

        In rglobs, * at the beginning of a path component means "any number of directories, including 0".
        So every time we see ^*, we need to output "**/*whatever".

        See https://github.com/pantsbuild/pants/blob/9832c8f6d8b60648cf906775506864aad0ffdb33/src/python/pants/source/wrapped_globs.py#L303
        for the original implementation.
        """
        components = rglob.split(os.path.sep)
        out: List[str] = []
        for component in components:
            if component == "**":
                if out and out[-1].startswith("**"):
                    continue
                out.append(component)
            elif component[0] == "*":
                if out and out[-1].startswith("**"):
                    # We want to translate *.py to **/*.py, not **/**/*.py
                    out.append(component)
                else:
                    out.append("**/" + component)
            else:
                out.append(component)
        return os.path.join(*out)

    @classmethod
    def parse(cls, glob_func: ast.Call, *, build_file: Path) -> Optional["GlobFunction"]:
        # NB: technically, glob arguments can be different than `globs`, `rglobs`, and `zglobs`, such
        # as using `set()` in an `exclude` clause. We don't try to handle this edge case.
        try:
            glob_type = GlobType(glob_func.func.id)  # type: ignore[attr-defined]
        except ValueError:
            logging.warning(
                f"Could not parse the glob type `{glob_func.func.id}` in {build_file} at "  # type: ignore[attr-defined]
                f"line {glob_func.lineno}. Please manually update."
            )
            return None
        if not all(isinstance(arg, ast.Str) for arg in glob_func.args):
            logging.warning(
                f"Could not parse the globs in {build_file} at line {glob_func.lineno}. Likely, you are "
                f"using variables instead of raw strings. Please manually update."
            )
            return None
        include_globs: List[str] = [arg.s for arg in glob_func.args]  # type: ignore[attr-defined]

        # Excludes are tricky...The optional `exclude` keyword is guaranteed to have a list as its
        # value, but that list can have any of these elements:
        #  * `str`
        #  * `glob`, `rglob`, or `zglob`
        #  * list of either of the above options
        exclude_globs: Optional[List[str]] = None
        exclude_arg: Optional[ast.keyword] = next(iter(glob_func.keywords), None)
        if exclude_arg is not None and isinstance(exclude_arg.value, ast.List):
            exclude_elements: List[Union[ast.Call, ast.Str, ast.List]] = exclude_arg.value.elts  # type: ignore[assignment]
            nested_exclude_elements: List[Union[ast.Call, ast.Str]] = list(
                itertools.chain.from_iterable(
                    nested_list.elts  # type: ignore[misc]
                    for nested_list in exclude_elements
                    if isinstance(nested_list, ast.List)
                )
            )
            combined_exclude_elements: List[Union[ast.Call, ast.Str]] = [
                element
                for element in (*exclude_elements, *nested_exclude_elements)
                # Lists are already flattened, so we want to remove them from this collection.
                if not isinstance(element, ast.List)
            ]
            if not all(isinstance(arg, (ast.Call, ast.Str)) for arg in combined_exclude_elements):
                logging.warning(
                    f"Could not parse the exclude globs in {build_file} at line {glob_func.lineno}. Likely, "
                    f"you are using variables instead of raw strings. Please manually update."
                )
                return None
            exclude_globs = [arg.s for arg in combined_exclude_elements if isinstance(arg, ast.Str)]
            exclude_glob_functions = (
                cls.parse(glob, build_file=build_file)
                for glob in combined_exclude_elements
                if isinstance(glob, ast.Call)
            )
            for exclude_glob_function in exclude_glob_functions:
                if exclude_glob_function is not None:
                    exclude_globs.extend(exclude_glob_function.includes)
            # We sort because of how we use recursion to evaluate `globs` within the `exclude` clause.
            # Without sorting, the results would appear out of order. Given this difficulty, it's not
            # worth trying to preserve the original order.
            exclude_globs.sort()

        if glob_type == GlobType.rglobs:
            include_globs = [cls.normalize_rglob(include) for include in include_globs]

        return GlobFunction(glob_type=glob_type, includes=include_globs, excludes=exclude_globs)

    def convert_to_sources_list(self, *, use_single_quotes: bool = False) -> str:
        escaped_excludes = [f"!{exclude}" for exclude in self.excludes or ()]
        quote = "'" if use_single_quotes else '"'
        quoted_globs = (f"{quote}{glob}{quote}" for glob in (*self.includes, *escaped_excludes))
        return f"[{', '.join(quoted_globs)}]"


def use_single_quotes(line: str) -> bool:
    num_single_quotes = sum(1 for c in line if c == "'")
    num_double_quotes = sum(1 for c in line if c == '"')
    return num_single_quotes > num_double_quotes


def warning_msg(
    *, build_file: Path, lineno: int, field_name: str, replacement: str, script_restriction: str
) -> str:
    return (
        f"Could not update {build_file} at line {lineno}. This script {script_restriction}. Please "
        f"manually update the `{field_name}` field to `{replacement}`."
    )


SCRIPT_RESTRICTIONS = {
    "no_comments": "cannot safely preserve comments",
    "no_bundles": "cannot safely update `bundles` fields",
    "sources_must_be_single_line": (
        "can only safely update the `sources` field when its declared on a single line"
    ),
    "sources_must_be_distinct_line": (
        "can only safely update the `sources` field when it's declared on a new distinct line, "
        "separate from the target type and other fields"
    ),
}


def generate_possibly_new_build(build_file: Path) -> Optional[List[str]]:
    """If any targets use `globs`, `rglobs`, or `zglobs`, this will return a replaced BUILD file."""
    original_text = build_file.read_text()
    original_text_lines = original_text.splitlines()
    updated_text_lines = original_text_lines.copy()

    targets: List[ast.Call] = [
        target.value
        for target in ast.parse(original_text).body
        if isinstance(target, ast.Expr) and isinstance(target.value, ast.Call)
    ]
    for target in targets:
        bundles_arg: Optional[ast.keyword] = next(
            (
                kwarg
                for kwarg in target.keywords
                if kwarg.arg == "bundles" and isinstance(kwarg.value, ast.List)
            ),
            None,
        )
        if bundles_arg is not None:
            bundle_funcs: List[ast.Call] = [
                element
                for element in bundles_arg.value.elts  # type: ignore[attr-defined]
                if isinstance(element, ast.Call) and element.func.id == "bundle"  # type: ignore[attr-defined]
            ]
            for bundle_func in bundle_funcs:
                # Every `bundle` is guaranteed to have a `fileset` defined.
                fileset_arg: ast.keyword = next(
                    kwarg for kwarg in bundle_func.keywords if kwarg.arg == "fileset"
                )
                if not isinstance(fileset_arg.value, ast.Call):
                    continue

                parsed_glob_function = GlobFunction.parse(fileset_arg.value, build_file=build_file)
                if parsed_glob_function is None:
                    continue

                lineno = fileset_arg.value.lineno
                original_line = updated_text_lines[lineno - 1].rstrip()
                formatted_replacement = parsed_glob_function.convert_to_sources_list(
                    use_single_quotes=use_single_quotes(original_line),
                )
                logging.warning(
                    warning_msg(
                        build_file=build_file,
                        lineno=lineno,
                        field_name="bundle(fileset=)",
                        replacement=formatted_replacement,
                        script_restriction=SCRIPT_RESTRICTIONS["no_bundles"],
                    )
                )
        sources_arg: Optional[ast.keyword] = next(
            (kwarg for kwarg in target.keywords if kwarg.arg == "sources"), None
        )
        if not sources_arg or not isinstance(sources_arg.value, ast.Call):
            continue

        parsed_glob_function = GlobFunction.parse(sources_arg.value, build_file=build_file)
        if parsed_glob_function is None:
            continue

        lineno: int = sources_arg.value.lineno  # type: ignore[no-redef]
        original_line = updated_text_lines[lineno - 1].rstrip()
        formatted_replacement = parsed_glob_function.convert_to_sources_list(
            use_single_quotes=use_single_quotes(original_line),
        )

        sources_warning = partial(
            warning_msg,
            build_file=build_file,
            lineno=lineno,
            field_name="sources",
            replacement=formatted_replacement,
        )

        if "#" in original_line:
            logging.warning(sources_warning(script_restriction=SCRIPT_RESTRICTIONS["no_comments"]))
            continue

        has_multiple_lines = not (original_line.endswith(")") or original_line[-2:] == "),")
        if has_multiple_lines:
            logging.warning(
                sources_warning(
                    script_restriction=SCRIPT_RESTRICTIONS["sources_must_be_single_line"]
                )
            )
            continue

        prefix = re.match(r"\s*sources\s*=\s*", original_line)
        if not prefix:
            logging.warning(
                sources_warning(
                    script_restriction=SCRIPT_RESTRICTIONS["sources_must_be_distinct_line"]
                )
            )
            continue

        updated_text_lines[lineno - 1] = f"{prefix[0]}{formatted_replacement},"

    return updated_text_lines if updated_text_lines != original_text_lines else None


def generate_diff(build_file: Path, new_content: List[str]) -> str:
    def green(s: str) -> str:
        return f"\x1b[32m{s}\x1b[0m"

    def red(s: str) -> str:
        return f"\x1b[31m{s}\x1b[0m"

    diff = unified_diff(
        build_file.read_text().splitlines(),
        new_content,
        fromfile=str(build_file),
        tofile=str(build_file),
    )
    msg = ""
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            msg += green(line)
        elif line.startswith("-") and not line.startswith("---"):
            msg += red(line)
        else:
            msg += line
        if not (line.startswith("+++") or line.startswith("---") or line.startswith("@@ ")):
            msg += "\n"
    return msg


if __name__ == "__main__":
    logging.basicConfig(format="[%(levelname)s]: %(message)s")
    try:
        main()
    except KeyboardInterrupt:
        pass
