# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE
from pants.core.goals.lint import LintFilesRequest, LintResult, Partitions
from pants.engine.fs import DigestContents, PathGlobs
from pants.engine.rules import Get, collect_rules, rule
from pants.option.option_types import DictOption, EnumOption, SkipOption
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized_method
from pants.util.strutil import help_text, softwrap

logger = logging.getLogger(__name__)


class DetailLevel(Enum):
    """How much detail about validation to emit to the console.

    none: Emit nothing.
    summary: Emit a summary only.
    nonmatching: Emit details for files that failed to match at least one pattern.
    name_only: Emit just the paths of files that failed to match at least one pattern.
    all: Emit details for all files.
    """

    none = "none"
    summary = "summary"
    nonmatching = "nonmatching"
    names = "names"
    all = "all"


@dataclass(frozen=True)
class PathPattern:
    name: str
    pattern: str
    inverted: bool = False
    content_encoding: str = "utf8"


@dataclass(frozen=True)
class ContentPattern:
    name: str
    pattern: str
    inverted: bool = False


@dataclass(frozen=True)
class ValidationConfig:
    path_patterns: tuple[PathPattern, ...]
    content_patterns: tuple[ContentPattern, ...]
    required_matches: FrozenDict[str, tuple[str]]  # path pattern name -> content pattern names.

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ValidationConfig:
        return cls(
            path_patterns=tuple(PathPattern(**kwargs) for kwargs in d["path_patterns"]),
            content_patterns=tuple(ContentPattern(**kwargs) for kwargs in d["content_patterns"]),
            required_matches=FrozenDict({k: tuple(v) for k, v in d["required_matches"].items()}),
        )


class RegexLintSubsystem(Subsystem):
    options_scope = "regex-lint"
    name = "regex-lint"
    help = help_text(
        """
        Lint your code using regex patterns, e.g. to check for copyright headers.

        To activate this with the `lint` goal, you must set `[regex-lint].config`.

        Unlike other linters, this can run on files not owned by targets, such as BUILD files.
        """
    )

    skip = SkipOption("lint")
    _config = DictOption[Any](
        help=softwrap(
            """
            Config schema is as follows:

                ```
                {
                'required_matches': {
                    'path_pattern1': [content_pattern1, content_pattern2],
                    'path_pattern2': [content_pattern1, content_pattern3],
                    ...
                },
                'path_patterns': [
                    {
                    'name': path_pattern1',
                    'pattern': <path regex pattern>,
                    'inverted': True|False (defaults to False),
                    'content_encoding': <encoding> (defaults to utf8)
                    },
                    ...
                ],
                'content_patterns': [
                    {
                    'name': 'content_pattern1',
                    'pattern': <content regex pattern>,
                    'inverted': True|False (defaults to False)
                    }
                    ...
                ]
                }
                ```

            Meaning: if a file matches some path pattern, its content must match all the
            corresponding content patterns.

            It's often helpful to load this config from a JSON or YAML file. To do that, set
            `[regex-lint].config = '@path/to/config.yaml'`, for example.
            """
        ),
        fromfile=True,
    )
    detail_level = EnumOption(
        default=DetailLevel.nonmatching,
        help="How much detail to include in the result.",
    )

    @memoized_method
    def get_multi_matcher(self) -> MultiMatcher | None:
        return MultiMatcher(ValidationConfig.from_dict(self._config)) if self._config else None


@dataclass(frozen=True)
class RegexMatchResult:
    """The result of running regex matches on a source file."""

    path: str
    matching: tuple
    nonmatching: tuple


class Matcher:
    """Class to match a single (possibly inverted) regex.

    Matches are allowed anywhere in the string (so really a "search" in the Python regex parlance).
    To anchor a match at the beginning of a string, use the ^ anchor. To anchor at the beginning of
    any line, use the ^ anchor along with the MULTILINE directive (?m).  See test for examples.
    """

    def __init__(self, pattern, inverted=False):
        self.compiled_regex = re.compile(pattern)
        self.inverted = inverted

    def matches(self, s):
        """Whether the pattern matches anywhere in the string s."""
        regex_matches = self.compiled_regex.search(s) is not None
        return not regex_matches if self.inverted else regex_matches


class PathMatcher(Matcher):
    """A matcher for matching file paths."""

    def __init__(self, path_pattern: PathPattern):
        super().__init__(path_pattern.pattern, path_pattern.inverted)
        # The expected encoding of the content of files whose paths match this pattern.
        self.content_encoding = path_pattern.content_encoding


class ContentMatcher(Matcher):
    """A matcher for matching file content."""

    def __init__(self, content_pattern: ContentPattern):
        super().__init__(content_pattern.pattern, content_pattern.inverted)


class MultiMatcher:
    def __init__(self, config: ValidationConfig) -> None:
        """Class to check multiple regex matching on files.

        :param dict config: Regex matching config (see above).
        """
        # Validate the pattern names mentioned in required_matches.
        path_patterns_used: set[str] = set()
        content_patterns_used: set[str] = set()
        for k, v in config.required_matches.items():
            path_patterns_used.add(k)
            if not isinstance(v, (tuple, list)):
                raise ValueError(
                    "Value for path pattern {} in required_matches must be tuple of "
                    "content pattern names, but was {}".format(k, v)
                )
            content_patterns_used.update(v)

        unknown_path_patterns = path_patterns_used.difference(
            pp.name for pp in config.path_patterns
        )
        if unknown_path_patterns:
            raise ValueError(
                "required_matches uses unknown path pattern names: "
                "{}".format(", ".join(sorted(unknown_path_patterns)))
            )

        unknown_content_patterns = content_patterns_used.difference(
            cp.name for cp in config.content_patterns
        )
        if unknown_content_patterns:
            raise ValueError(
                "required_matches uses unknown content pattern names: "
                "{}".format(", ".join(sorted(unknown_content_patterns)))
            )

        self._path_matchers = {pp.name: PathMatcher(pp) for pp in config.path_patterns}
        self._content_matchers = {cp.name: ContentMatcher(cp) for cp in config.content_patterns}
        self._required_matches = config.required_matches

    def check_content(
        self, path: str, content: bytes, content_pattern_names: Iterable[str], encoding: str
    ) -> RegexMatchResult:
        matching = []
        nonmatching = []
        for content_pattern_name in content_pattern_names:
            if self._content_matchers[content_pattern_name].matches(content.decode(encoding)):
                matching.append(content_pattern_name)
            else:
                nonmatching.append(content_pattern_name)
        return RegexMatchResult(path, tuple(matching), tuple(nonmatching))

    def get_applicable_content_pattern_names(self, path: str) -> tuple[set[str], str | None]:
        """Return the content patterns applicable to a given path.

        Returns a tuple (applicable_content_pattern_names, content_encoding).

        If path matches no path patterns, the returned content_encoding will be None (and
        applicable_content_pattern_names will be empty).
        """
        encodings = set()
        applicable_content_pattern_names: set[str] = set()
        for path_pattern_name, content_pattern_names in self._required_matches.items():
            m = self._path_matchers[path_pattern_name]
            if m.matches(path):
                encodings.add(m.content_encoding)
                applicable_content_pattern_names.update(content_pattern_names)
        if len(encodings) > 1:
            raise ValueError(
                "Path matched patterns with multiple content encodings ({}): {}".format(
                    ", ".join(sorted(encodings)), path
                )
            )
        content_encoding = next(iter(encodings)) if encodings else None
        return applicable_content_pattern_names, content_encoding


class RegexLintRequest(LintFilesRequest):
    tool_subsystem = RegexLintSubsystem


@rule
async def partition_inputs(
    request: RegexLintRequest.PartitionRequest, regex_lint_subsystem: RegexLintSubsystem
) -> Partitions[str, Any]:
    multi_matcher = regex_lint_subsystem.get_multi_matcher()
    if multi_matcher is None:
        return Partitions()

    applicable_file_paths = []
    for fp in request.files:
        content_pattern_names, encoding = multi_matcher.get_applicable_content_pattern_names(fp)
        if content_pattern_names and encoding:
            applicable_file_paths.append(fp)

    return Partitions.single_partition(applicable_file_paths)


@rule(desc="Lint with regex patterns", level=LogLevel.DEBUG)
async def lint_with_regex_patterns(
    request: RegexLintRequest.Batch[str, Any], regex_lint_subsystem: RegexLintSubsystem
) -> LintResult:
    multi_matcher = regex_lint_subsystem.get_multi_matcher()
    assert multi_matcher is not None
    file_to_content_pattern_names_and_encoding = {}
    for fp in request.elements:
        content_pattern_names, encoding = multi_matcher.get_applicable_content_pattern_names(fp)
        assert content_pattern_names and encoding
        file_to_content_pattern_names_and_encoding[fp] = (content_pattern_names, encoding)

    digest_contents = await Get(
        DigestContents, PathGlobs(globs=file_to_content_pattern_names_and_encoding.keys())
    )

    result = []
    for file_content in digest_contents:
        content_patterns, encoding = file_to_content_pattern_names_and_encoding[file_content.path]
        result.append(
            multi_matcher.check_content(
                file_content.path, file_content.content, content_patterns, encoding
            )
        )

    stdout = ""
    detail_level = regex_lint_subsystem.detail_level
    num_matched_all = 0
    num_nonmatched_some = 0
    for rmr in sorted(result, key=lambda rmr: rmr.path):
        if not rmr.matching and not rmr.nonmatching:
            continue
        if detail_level == DetailLevel.names:
            if rmr.nonmatching:
                stdout += f"{rmr.path}\n"
            continue

        if rmr.nonmatching:
            icon = "X"
            num_nonmatched_some += 1
        else:
            icon = "V"
            num_matched_all += 1
        matched_msg = " Matched: {}".format(",".join(rmr.matching)) if rmr.matching else ""
        nonmatched_msg = (
            " Didn't match: {}".format(",".join(rmr.nonmatching)) if rmr.nonmatching else ""
        )
        if detail_level == DetailLevel.all or (
            detail_level == DetailLevel.nonmatching and nonmatched_msg
        ):
            stdout += f"{icon} {rmr.path}:{matched_msg}{nonmatched_msg}\n"

    if detail_level not in (DetailLevel.none, DetailLevel.names):
        if stdout:
            stdout += "\n"
        stdout += f"{num_matched_all} files matched all required patterns.\n"
        stdout += f"{num_nonmatched_some} files failed to match at least one required pattern."

    exit_code = PANTS_FAILED_EXIT_CODE if num_nonmatched_some else PANTS_SUCCEEDED_EXIT_CODE
    return LintResult(exit_code, stdout, "", RegexLintSubsystem.options_scope)


def rules():
    return []
    # return (*collect_rules(), *RegexLintRequest.rules())
