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


# !inc[start-at=void main&end-before=private HelloMain](HelloMain.java)
INCLUDE_PATTERN = r'!inc(\[(?P<params>[^]]*)\])?\((?P<path>[^' + '\n' + r']*)\)'

INCLUDE_RECOGNIZED_PARAMS = frozenset([
  'start-after', 'start-at', 'end-before', 'end-at', 'lines'])

LINES_PATTERN = re.compile(r'\A([1-9][0-9]*)-([1-9][0-9]*)\Z')


def choose_include_text(s, params, source_path):
  """Given the contents of a file and !inc[these params], return matching lines

  If there was a problem matching parameters, return empty list.

  :param s: file's text
  :param params: string like "start-at=foo&end-at=bar"
  :param source_path: path to source .md. Useful in error messages
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
      raise TaskError('Invalid include directive "{0}" in params "{1}"'
                      ' from {2}'.format(param, params, source_path))
    params_dict[param] = value

  chosen_lines = []
  try:
    if 'lines' in params_dict:
      lines_arg = params_dict['lines']
      chosen_lines = include_by_line_range(source_lines, lines_arg, params_dict)
    else:
      chosen_lines = include_by_text_match(source_lines, params_dict)
  except TaskError as include_error:
    raise TaskError('Error: {0} (in params "{1}" from {2})'
                    .format(include_error, params, source_path))
  return '\n'.join(chosen_lines)


def include_by_line_range(source_lines, line_range_arg, params_dict):
  # 'lines' should be the only parameter specified
  conflicts = [(p, params_dict[p]) for p in params_dict if p != 'lines']
  if len(conflicts) > 0:
    error_msgs = ', '.join(['"{0}={1}"'.format(p, v) for (p, v) in conflicts])
    raise TaskError('"lines" directive conflicts with other directives: [{0}]'
                    .format(error_msgs))

  # validate the line range
  lines_match = LINES_PATTERN.match(line_range_arg)
  if lines_match is None:
    raise TaskError('Invalid line range "{0}" (should match "{1}") for "lines"'
                    .format(line_range_arg, LINES_PATTERN.pattern))
  [line_start, line_end] = (int(g) for g in lines_match.groups())
  # LINES_PATTERN does not allow 0 or negative numbers
  if line_end < line_start:
    raise TaskError('Invalid end line "{0}" (should be >= {1}, the start line)'
                    ' from "{2}" for "lines"'
                    .format(line_end, line_start, line_range_arg))
  nlines = len(source_lines)
  if line_end > nlines:
    raise TaskError('Invalid end line "{0}"'
                    ' (should be <= {1}, the number of lines in the source)'
                    ' from "{2}" for "lines"'
                    .format(line_end, nlines, line_range_arg))

  # line range arguments start at 1
  return source_lines[(line_start - 1):line_end]


def include_by_text_match(source_lines, params_dict):
  chosen_lines = []
  # two loops, one waits to "start recording", one "records"
  for line_ix in range(0, len(source_lines)):
    line = source_lines[line_ix]
    if ('start-at' not in params_dict) and ('start-after' not in params_dict):
      # if we didn't set a start-* param, don't wait to start
      break
    if 'start-at' in params_dict and params_dict['start-at'] in line:
      break
    if 'start-after' in params_dict and params_dict['start-after'] in line:
      line_ix += 1
      break
  else:
    # never started recording:
    return ''
  for line_ix in range(line_ix, len(source_lines)):
    line = source_lines[line_ix]
    if 'end-before' in params_dict and params_dict['end-before'] in line:
      break
    chosen_lines.append(line)
    if 'end-at' in params_dict and params_dict['end-at'] in line:
      break
  else:
    if 'end-before' in params_dict or 'end-at' in params_dict:
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
      raise IOError('Markdown file {0} tried to include file {1}, got '
                    '{2}'.format(self.source_path,
                                 rel_include_path,
                                 e.strerror))
    include_text = choose_include_text(file_text, params, self.source_path)
    if not include_text:
      raise TaskError('Markdown file {0} tried to include file {1} but '
                      'filtered out everything'.format(self.source_path,
                                                       rel_include_path))
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
