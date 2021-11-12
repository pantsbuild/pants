# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from enum import Enum
from typing import Any, cast

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.fs import Digest, DigestContents, SpecsSnapshot
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import Get, collect_rules, goal_rule
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized_method


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


class ValidateSubsystem(GoalSubsystem):
    name = "validate"
    help = "Validate sources against regexes."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--detail-level",
            type=DetailLevel,
            default=DetailLevel.nonmatching,
            help="How much detail to emit to the console.",
        )

    @property
    def detail_level(self) -> DetailLevel:
        return cast(DetailLevel, self.options.detail_level)


class Validate(Goal):
    subsystem_cls = ValidateSubsystem


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


class SourceFileValidation(Subsystem):
    options_scope = "sourcefile-validation"
    help = "Configuration for source file validation."

    @classmethod
    def register_options(cls, register):
        schema_help = textwrap.dedent(
            """\
            Config schema is as follows:

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

            Meaning: if a file matches some path pattern, its content must match all
            the corresponding content patterns.
            """
        )
        super().register_options(register)
        register("--config", type=dict, fromfile=True, help=schema_help)

    @memoized_method
    def get_multi_matcher(self):
        return MultiMatcher(ValidationConfig.from_dict(self.options.config))


@dataclass(frozen=True)
class RegexMatchResult:
    """The result of running regex matches on a source file."""

    path: str
    matching: tuple
    nonmatching: tuple


class RegexMatchResults(Collection[RegexMatchResult]):
    pass


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
    def __init__(self, config: ValidationConfig):
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

    def check_source_file(self, path, content):
        content_pattern_names, encoding = self.get_applicable_content_pattern_names(path)
        matching, nonmatching = self.check_content(content_pattern_names, content, encoding)
        return RegexMatchResult(path, matching, nonmatching)

    def check_content(self, content_pattern_names, content, encoding):
        """Check which of the named patterns matches the given content.

        Returns a pair (matching, nonmatching), in which each element is a tuple of pattern names.

        :param iterable content_pattern_names: names of content patterns to check.
        :param bytes content: the content to check.
        :param str encoding: the expected encoding of content.
        """
        if not content_pattern_names or not encoding:
            return (), ()

        matching = []
        nonmatching = []
        for content_pattern_name in content_pattern_names:
            if self._content_matchers[content_pattern_name].matches(content.decode(encoding)):
                matching.append(content_pattern_name)
            else:
                nonmatching.append(content_pattern_name)
        return tuple(matching), tuple(nonmatching)

    def get_applicable_content_pattern_names(self, path):
        """Return the content patterns applicable to a given path.

        Returns a tuple (applicable_content_pattern_names, content_encoding).

        If path matches no path patterns, the returned content_encoding will be None (and
        applicable_content_pattern_names will be empty).
        """
        encodings = set()
        applicable_content_pattern_names = set()
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


# TODO: Consider switching this to `lint`. The main downside is that we would no longer be able to
#  run on files with no owning targets, such as running on BUILD files.
@goal_rule
async def validate(
    console: Console,
    specs_snapshot: SpecsSnapshot,
    validate_subsystem: ValidateSubsystem,
    source_file_validation: SourceFileValidation,
) -> Validate:
    multi_matcher = source_file_validation.get_multi_matcher()
    digest_contents = await Get(DigestContents, Digest, specs_snapshot.snapshot.digest)
    regex_match_results = RegexMatchResults(
        multi_matcher.check_source_file(file_content.path, file_content.content)
        for file_content in sorted(digest_contents, key=lambda fc: fc.path)
    )

    detail_level = validate_subsystem.detail_level
    num_matched_all = 0
    num_nonmatched_some = 0
    for rmr in regex_match_results:
        if not rmr.matching and not rmr.nonmatching:
            continue
        if detail_level == DetailLevel.names:
            if rmr.nonmatching:
                console.print_stdout(rmr.path)
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
            console.print_stdout(f"{icon} {rmr.path}:{matched_msg}{nonmatched_msg}")

    if detail_level not in (DetailLevel.none, DetailLevel.names):
        console.print_stdout(f"\n{num_matched_all} files matched all required patterns.")
        console.print_stdout(
            f"{num_nonmatched_some} files failed to match at least one required pattern."
        )

    if num_nonmatched_some:
        exit_code = PANTS_FAILED_EXIT_CODE
    else:
        exit_code = PANTS_SUCCEEDED_EXIT_CODE
    return Validate(exit_code)


def rules():
    return collect_rules()
