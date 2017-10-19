# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import sys

import markdown
from docutils.core import publish_parts
from pygments import highlight
from pygments.formatters.html import HtmlFormatter
from pygments.lexers import PythonLexer, TextLexer, guess_lexer_for_filename
from pygments.util import ClassNotFound
from six.moves import range

from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_open


def emit_codehighlight_css(path, style):
  with safe_open(path, 'w') as css:
    css.write((HtmlFormatter(style=style)).get_style_defs('.codehilite'))
  return path


WIKILINKS_PATTERN = r'\[\[([^\]]+)\]\]'


class WikilinksPattern(markdown.inlinepatterns.Pattern):
  def __init__(self, build_url, markdown_instance=None):
    # Old-style class, so we must invoke __init__ this way.
    markdown.inlinepatterns.Pattern.__init__(self, WIKILINKS_PATTERN, markdown_instance)
    self.build_url = build_url

  def handleMatch(self, m):
    alias, url = self.build_url(m.group(2).strip())
    el = markdown.util.etree.Element('a')
    el.set('href', url)
    el.text = markdown.util.AtomicString(alias)
    return el


class WikilinksExtension(markdown.Extension):
  def __init__(self, build_url, configs=None):
    # Old-style class, so we must invoke __init__ this way.
    markdown.Extension.__init__(self, configs or {})
    self.build_url = build_url

  def extendMarkdown(self, md, md_globals):
    md.inlinePatterns['wikilinks'] = WikilinksPattern(self.build_url, md)


class IncludeParamParseError(Exception):
  """Raised when a parameter in an !inc directive is invalid in some way."""


# e.g. !inc[start-at=void main&end-before=private HelloMain](HelloMain.java)
INCLUDE_PATTERN = r'!inc(\[(?P<params>[^]]*)\])?\((?P<path>[^' + '\n' + r']*)\)'

INCLUDE_RECOGNIZED_PARAMS = frozenset([
  'start-after', 'start-at', 'end-before', 'end-at', 'lines'])

LINES_PATTERN = re.compile(r'\A([1-9][0-9]*)-([1-9][0-9]*)\Z')


def choose_include_text(s, params):
  """Given the contents of a file and !inc[these params], return matching lines

  FIXME: this is an incorrect description!
  If there was a problem matching parameters, return empty list.

  :param s: file's text
  :param params: string like "start-at=foo&end-at=bar"
  """
  source_lines = s.splitlines()
  params_dict = {}

  for term in params.split("&"):
    if '=' in term:
      param, value = [p.strip() for p in term.split('=', 1)]
    else:
      param, value = term.strip(), ''
    if not param: continue
    if param not in INCLUDE_RECOGNIZED_PARAMS:
      valid_params = ["'{0}'".format(p) for p in INCLUDE_RECOGNIZED_PARAMS]
      raise IncludeParamParseError(
        'Invalid parameter name "{0}": valid parameters are: [{1}].'
        .format(param, ', '.join(valid_params)))
    params_dict[param] = value

  chosen_lines = []
  # do any validation/parsing here and pass parsed values directly to helper
  if 'lines' not in params_dict:
    chosen_lines = include_by_text_match(
      source_lines,
      params_dict.get('start-after'),
      params_dict.get('start-at'),
      params_dict.get('end-before'),
      params_dict.get('end-at'))
  else:
    line_range_arg = params_dict['lines']
    if len(params_dict) > 1:
      raise IncludeParamParseError(
        'Parameter conflict: "lines" cannot be used except by itself')
    lines_match = LINES_PATTERN.match(line_range_arg)
    if lines_match is None:
      raise IncludeParamParseError(
        'Invalid line range "{0}" provided for parameter "lines"'
        ': should match "{1}"'
        .format(line_range_arg, LINES_PATTERN.pattern))
    [line_start, line_end] = (int(g) for g in lines_match.groups())
    # LINES_PATTERN does not allow 0 or negative numbers
    if line_end < line_start:
      raise IncludeParamParseError(
        'Invalid end line "{0}" in argument "{1}" for parameter "lines"'
        ': should be >= {2}, the start line'
        .format(line_end, line_range_arg, line_start))
    nlines = len(source_lines)
    if line_end > nlines:
      raise IncludeParamParseError(
        'Invalid end line "{0}" in argument "{1}" for parameter "lines"'
        ': should be <= {1}, the number of lines in the source text'
        .format(line_end, line_range_arg, nlines))
    # line range arguments start at 1
    chosen_lines = source_lines[(line_start - 1):line_end]

  return '\n'.join(chosen_lines)


def include_by_text_match(source_lines, start_after, start_at, end_before, end_at):
  chosen_lines = []
  # two loops, one waits to "start recording", one "records"
  for line_ix in range(0, len(source_lines)):
    line = source_lines[line_ix]
    if start_at is None and start_after is None:
      # if we didn't set a start-* param, don't wait to start
      break
    if start_at is not None and start_at in line:
      break
    if start_after is not None and start_after in line:
      line_ix += 1
      break
  else:
    # never started recording:
    return ''
  for line_ix in range(line_ix, len(source_lines)):
    line = source_lines[line_ix]
    if end_before is not None and end_before in line:
      break
    chosen_lines.append(line)
    if end_at is not None and end_at in line:
      break
  else:
    if end_before is not None or end_at is not None:
      # we had an end- filter, but never encountered it.
      return ''
  return chosen_lines


class IncludeExcerptPattern(markdown.inlinepatterns.Pattern):
  def __init__(self, source_path=None):
    """
    :param string source_path: Path to source `.md` file.
    """
    # Old-style class, so we must invoke __init__ this way.
    markdown.inlinepatterns.Pattern.__init__(self, INCLUDE_PATTERN)
    self.source_path = source_path

  def handleMatch(self, match):
    params = match.group('params') or ''
    rel_include_path = match.group('path')
    source_dir = os.path.dirname(self.source_path)
    include_path = os.path.join(source_dir, rel_include_path)
    try:
      with open(include_path) as include_file:
        file_text = include_file.read()
    except IOError as e:
      raise IOError(
        'Markdown file {0} tried to include file {1}, but got "{2}"'
        .format(self.source_path, rel_include_path, e.strerror))
    try:
      include_text = choose_include_text(file_text, params)
    except IncludeParamParseError as e:
      raise TaskError(
        'Markdown file {0} tried to include file {1}'
        ' with params "{2}", but got "{3}"'
        .format(self.source_path, rel_include_path, params, e.strerror))
    if not include_text:
      raise TaskError('Markdown file {0} tried to include file {1}'
                      ' with params "{2}", but filtered out everything'
                      .format(self.source_path, rel_include_path, params))
    el = markdown.util.etree.Element('div')
    el.set('class', 'md-included-snippet')
    try:
      lexer = guess_lexer_for_filename(include_path, file_text)
    except ClassNotFound:
      # e.g., ClassNotFound: no lexer for filename u'BUILD' found
      if 'BUILD' in include_path:
        lexer = PythonLexer()
      else:
        lexer = TextLexer()  # the boring plain-text lexer

    html_snippet = highlight(include_text,
                             lexer,
                             HtmlFormatter(cssclass='codehilite'))
    el.text = html_snippet
    return el


class IncludeExcerptExtension(markdown.Extension):
  def __init__(self, source_path, configs=None):
    # Old-style class, so we must invoke __init__ this way.
    markdown.Extension.__init__(self, configs or {})
    self.source_path = source_path

  def extendMarkdown(self, md, md_globals):
    md.inlinePatterns.add('excerpt',
                          IncludeExcerptPattern(source_path=self.source_path),
                          '_begin')


def page_to_html_path(page):
  """Given a page target, return partial path for an output `.html`."""
  source_path = page.sources_relative_to_buildroot()[0]
  return os.path.splitext(source_path)[0] + ".html"


def rst_to_html(in_rst, stderr):
  """Renders HTML from an RST fragment.

  :param string in_rst: An rst formatted string.
  :param stderr: An open stream to use for docutils stderr output.
  :returns: A tuple of (html rendered rst, return code)
  """
  if not in_rst:
    return '', 0

  # Unfortunately, docutils is really setup for command line use.
  # We're forced to patch the bits of sys its hardcoded to use so that we can call it in-process
  # and still reliably determine errors.
  # TODO(John Sirois): Move to a subprocess execution model utilizing a docutil chroot/pex.
  orig_sys_exit = sys.exit
  orig_sys_stderr = sys.stderr
  returncodes = []
  try:
    sys.exit = returncodes.append
    sys.stderr = stderr
    pp = publish_parts(in_rst,
                       writer_name='html',
                       # Report and exit at level 2 (warnings) or higher.
                       settings_overrides=dict(exit_status_level=2, report_level=2),
                       enable_exit_status=True)
  finally:
    sys.exit = orig_sys_exit
    sys.stderr = orig_sys_stderr

  return_value = ''
  if 'title' in pp and pp['title']:
    return_value += '<title>{0}</title>\n<p style="font: 200% bold">{0}</p>\n'.format(pp['title'])
  return_value += pp['body'].strip()
  return return_value, returncodes.pop() if returncodes else 0
