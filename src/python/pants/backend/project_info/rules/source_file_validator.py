# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import itertools
import re

from future.utils import text_type

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE
from pants.engine.console import Console
from pants.engine.fs import Digest, FilesContent
from pants.engine.goal import Goal
from pants.engine.legacy.graph import HydratedTarget, HydratedTargets
from pants.engine.objects import Collection
from pants.engine.rules import console_rule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method
from pants.util.objects import datatype, enum


class DetailLevel(enum(['none', 'summary', 'nonmatching', 'all'])):
  """How much detail about validation to emit to the console.

  none: Emit nothing.
  summary: Emit a summary only.
  nonmatching: Emit details for source files that failed to match at least one required pattern.
  all: Emit details for all source files.
  """
  pass


class Validate(Goal):
  name = 'validate'

  @classmethod
  def register_options(cls, register):
    super(Validate, cls).register_options(register)
    register('--detail-level', type=DetailLevel, default=DetailLevel.nonmatching,
             help='How much detail to emit to the console.')


class SourceFileValidation(Subsystem):
  options_scope = 'sourcefile-validation'

  @classmethod
  def register_options(cls, register):
    super(SourceFileValidation, cls).register_options(register)
    # Config schema is as follows:
    #
    # {
    #   'path_patterns': {
    #     'path_pattern1': {
    #       'pattern': <path regex pattern>,
    #       'inverted': True|False (defaults to False),
    #       'content_encoding': <encoding> (defaults to utf8)
    #     }
    #     ...
    #   },
    #   'content_patterns': {
    #     'content_pattern1': {
    #       'pattern': <content regex pattern>,
    #       'inverted': True|False (defaults to False)
    #     }
    #     ...
    #   },
    #   'required_matches': {
    #     'path_pattern1': [content_pattern1, content_pattern2],
    #     'path_pattern2': [content_pattern1, content_pattern3],
    #     ...
    #   }
    # }
    #
    # Meaning: if a file matches some path pattern, its content must match all the corresponding
    # content patterns.
    register('--config', type=dict, fromfile=True,
             # TODO: Replace "See documentation" with actual URL, once we have some.
             help='Source file regex matching config.  See documentation for config schema.')

  @memoized_method
  def get_multi_matcher(self):
    return MultiMatcher(self.get_options().config)


class RegexMatchResult(datatype([
  ('path', text_type), ('matching', tuple), ('nonmatching', tuple)
])):
  """The result of running regex matches on a source file."""


RegexMatchResults = Collection.of(RegexMatchResult)


class Matcher(object):
  """Class to match a single (possibly inverted) regex.

  Matches are allowed anywhere in the string (so really a "search" in the Python regex parlance).
  To anchor a match at the beginning of a string, use the ^ anchor. To anchor at the beginning
  of any line, use the ^ anchor along with the MULTILINE directive (?m).  See test for examples.
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
  
  def __init__(self, pattern, inverted=False, content_encoding='utf8'):
    super(PathMatcher, self).__init__(pattern, inverted)
    # The expected encoding of the content of files whose paths match this pattern.
    self.content_encoding = content_encoding


class ContentMatcher(Matcher):
  """A matcher for matching file content."""
  pass


class MultiMatcher(object):
  def __init__(self, config):
    """Class to check multiple regex matching on files.

    :param dict config: Regex matching config (see above).
    """
    path_patterns = config.get('path_patterns', {})
    content_patterns = config.get('content_patterns', {})
    required_matches = config.get('required_matches', {})
    # Validate the pattern names mentioned in required_matches.
    path_patterns_used = set()
    content_patterns_used = set()
    for k, v in required_matches.items():
      path_patterns_used.add(k)
      if not isinstance(v, (tuple, list)):
        raise ValueError('Value for path pattern {} in required_matches must be tuple of '
                         'content pattern names, but was {}'.format(k, v))
      content_patterns_used.update(v)

    unknown_path_patterns = path_patterns_used.difference(path_patterns.keys())
    if unknown_path_patterns:
      raise ValueError('required_matches uses unknown path pattern names: '
                       '{}'.format(', '.join(sorted(unknown_path_patterns))))

    unknown_content_patterns = content_patterns_used.difference(content_patterns.keys())
    if unknown_content_patterns:
      raise ValueError('required_matches uses unknown content pattern names: '
                       '{}'.format(', '.join(sorted(unknown_content_patterns))))

    self._path_matchers = {k: PathMatcher(**v) for k, v in path_patterns.items()}
    self._content_matchers = {k: ContentMatcher(**v) for k, v in content_patterns.items()}
    self._required_matches = required_matches

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
      raise ValueError('Path matched patterns with multiple content encodings ({}): {}'.format(
        ', '.join(sorted(encodings)), path
      ))
    content_encoding = next(iter(encodings)) if encodings else None
    return applicable_content_pattern_names, content_encoding


# TODO: Switch this to `lint` once we figure out a good way for v1 tasks and v2 rules
# to share goal names.
@console_rule(Validate, [Console, HydratedTargets, Validate.Options])
def validate(console, hydrated_targets, validate_options):
  per_tgt_rmrs = yield [Get(RegexMatchResults, HydratedTarget, ht) for ht in hydrated_targets]
  regex_match_results = list(itertools.chain(*per_tgt_rmrs))

  detail_level = validate_options.values.detail_level
  regex_match_results = sorted(regex_match_results, key=lambda x: x.path)
  num_matched_all = 0
  num_nonmatched_some = 0
  for rmr in regex_match_results:
    if not rmr.matching and not rmr.nonmatching:
      continue
    if rmr.nonmatching:
      icon = 'X'
      num_nonmatched_some += 1
    else:
      icon = 'V'
      num_matched_all += 1
    matched_msg = ' Matched: {}'.format(','.join(rmr.matching)) if rmr.matching else ''
    nonmatched_msg = (" Didn't match: {}".format(','.join(rmr.nonmatching))
                      if rmr.nonmatching else '')
    if (detail_level == DetailLevel.all or
        (detail_level == DetailLevel.nonmatching and nonmatched_msg)):
      console.print_stdout("{} {}:{}{}".format(icon, rmr.path, matched_msg, nonmatched_msg))

  if detail_level != DetailLevel.none:
    console.print_stdout('\n{} files matched all required patterns.'.format(num_matched_all))
    console.print_stdout('{} files failed to match at least one required pattern.'.format(
      num_nonmatched_some))

  if num_nonmatched_some:
    console.print_stderr('Files failed validation.')
    exit_code = PANTS_FAILED_EXIT_CODE
  else:
    exit_code = PANTS_SUCCEEDED_EXIT_CODE
  yield Validate(exit_code)


@rule(RegexMatchResults, [HydratedTarget, SourceFileValidation])
def match_regexes_for_one_target(hydrated_target, source_file_validation):
  multi_matcher = source_file_validation.get_multi_matcher()
  rmrs = []
  if hasattr(hydrated_target.adaptor, 'sources'):
    files_content = yield Get(FilesContent,
                              Digest, hydrated_target.adaptor.sources.snapshot.directory_digest)
    for file_content in files_content:
      rmrs.append(multi_matcher.check_source_file(file_content.path, file_content.content))
  yield RegexMatchResults(rmrs)


def rules():
  return [
    validate,
    match_regexes_for_one_target,
    optionable_rule(SourceFileValidation),
  ]
