# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import codecs
import os
import re
import sys

import markdown
from docutils.core import publish_parts
from pkg_resources import resource_string
from pygments import highlight
from pygments.formatters.html import HtmlFormatter
from pygments.lexers import PythonLexer, TextLexer, guess_lexer_for_filename
from pygments.styles import get_all_styles
from pygments.util import ClassNotFound
from six.moves import range

from pants.backend.core.targets.doc import Page
from pants.backend.core.tasks.task import Task
from pants.base.address import Address
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.generator import Generator
from pants.base.workunit import WorkUnitLabel
from pants.binaries import binary_util
from pants.util.dirutil import safe_mkdir, safe_open


def emit_codehighlight_css(path, style):
  with safe_open(path, 'w') as css:
    css.write((HtmlFormatter(style=style)).get_style_defs('.codehilite'))
  return path


WIKILINKS_PATTERN = r'\[\[([^\]]+)\]\]'


class WikilinksPattern(markdown.inlinepatterns.Pattern):
  def __init__(self, build_url, markdown_instance=None):
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
    markdown.Extension.__init__(self, configs or {})
    self.build_url = build_url

  def extendMarkdown(self, md, md_globals):
    md.inlinePatterns['wikilinks'] = WikilinksPattern(self.build_url, md)


# !inc[start-at=void main&end-before=private HelloMain](HelloMain.java)
INCLUDE_PATTERN = r'!inc(\[(?P<params>[^]]*)\])?\((?P<path>[^' + '\n' + r']*)\)'


def choose_include_text(s, params, source_path):
  """Given the contents of a file and !inc[these params], return matching lines

  If there was a problem matching parameters, return empty list.

  :param s: file's text
  :param params: string like "start-at=foo&end-at=bar"
  :param source_path: path to source .md. Useful in error messages
  """
  lines = s.splitlines()
  start_after = None
  start_at = None
  end_before = None
  end_at = None

  for term in params.split("&"):
    if '=' in term:
      param, value = [p.strip() for p in term.split('=', 1)]
    else:
      param, value = term.strip(), ''
    if not param: continue
    if param == "start-after":
      start_after = value
    elif param == "start-at":
      start_at = value
    elif param == "end-before":
      end_before = value
    elif param == "end-at":
      end_at = value
    else:
      raise TaskError('Invalid include directive "{0}"'
                      ' in {1}'.format(params, source_path))

  chosen_lines = []
  # two loops, one waits to "start recording", one "records"
  for line_ix in range(0, len(lines)):
    line = lines[line_ix]
    if (not start_at) and (not start_after):
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
  for line_ix in range(line_ix, len(lines)):
    line = lines[line_ix]
    if end_before is not None and end_before in line:
      break
    chosen_lines.append(line)
    if end_at is not None and end_at in line:
      break
  else:
    if (end_before or end_at):
      # we had an end- filter, but never encountered it.
      return ''
  return '\n'.join(chosen_lines)


class IncludeExcerptPattern(markdown.inlinepatterns.Pattern):
  def __init__(self, source_path=None):
    """
    :param string source_path: Path to source `.md` file.
    """
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


class MarkdownToHtml(Task):

  @classmethod
  def register_options(cls, register):
    register('--code-style', choices=list(get_all_styles()), default='friendly',
             fingerprint=True,
             help='Use this stylesheet for code highlights.')
    register('--open', action='store_true',
             help='Open the generated documents in a browser.')
    register('--fragment', action='store_true',
             fingerprint=True,
             help='Generate a fragment of html to embed in a page.')
    register('--ignore-failure', default=False, action='store_true',
             fingerprint=True,
             help='Do not consider rendering errors to be build errors.')

  @classmethod
  def product_types(cls):
    return ['markdown_html', 'wiki_html']

  def __init__(self, *args, **kwargs):
    super(MarkdownToHtml, self).__init__(*args, **kwargs)
    self._templates_dir = os.path.join('templates', 'markdown')
    self.open = self.get_options().open
    self.fragment = self.get_options().fragment
    self.code_style = self.get_options().code_style

  def execute(self):
    # TODO(John Sirois): consider adding change detection

    outdir = os.path.join(self.get_options().pants_distdir, 'markdown')
    css_path = os.path.join(outdir, 'css', 'codehighlight.css')
    css = emit_codehighlight_css(css_path, self.code_style)
    if css:
      self.context.log.info('Emitted {}'.format(css))

    def is_page(target):
      return isinstance(target, Page)

    roots = set()
    interior_nodes = set()
    if self.open:
      dependencies_by_page = self.context.dependents(on_predicate=is_page, from_predicate=is_page)
      roots.update(dependencies_by_page.keys())
      for dependencies in dependencies_by_page.values():
        interior_nodes.update(dependencies)
        roots.difference_update(dependencies)
      for page in self.context.targets(is_page):
        # There are no in or out edges so we need to show show this isolated page.
        if not page.dependencies and page not in interior_nodes:
          roots.add(page)

    with self.context.new_workunit(name='render', labels=[WorkUnitLabel.MULTITOOL]):
      plaingenmap = self.context.products.get('markdown_html')
      wikigenmap = self.context.products.get('wiki_html')
      show = []
      for page in self.context.targets(is_page):
        def process_page(key, outdir, url_builder, genmap, fragment=False):
          if page.format == 'rst':
            with self.context.new_workunit(name='rst') as workunit:
              html_path = self.process_rst(
                workunit,
                page,
                os.path.join(outdir, page_to_html_path(page)),
                os.path.join(page.payload.sources.rel_path, page.source),
                self.fragment or fragment,
              )
          else:
            with self.context.new_workunit(name='md'):
              html_path = self.process_md(
                os.path.join(outdir, page_to_html_path(page)),
                os.path.join(page.payload.sources.rel_path, page.source),
                self.fragment or fragment,
                url_builder,
                css=css,
              )
          self.context.log.info('Processed {} to {}'.format(page.source, html_path))
          relpath = os.path.relpath(html_path, outdir)
          genmap.add(key, outdir, [relpath])
          return html_path

        def url_builder(linked_page):
          dest = page_to_html_path(linked_page)
          src_dir = os.path.dirname(page_to_html_path(page))
          return linked_page.name, os.path.relpath(dest, src_dir)

        page_path = os.path.join(outdir, 'html')
        html = process_page(page, page_path, url_builder, plaingenmap)
        if css and not self.fragment:
          plaingenmap.add(page, self.workdir, list(css_path))
        if self.open and page in roots:
          show.append(html)

        if page.provides:
          for wiki in page.provides:
            basedir = os.path.join(self.workdir, str(hash(wiki)))
            process_page((wiki, page), basedir, wiki.wiki.url_builder, wikigenmap, fragment=True)

    if show:
      binary_util.ui_open(*show)

  PANTS_LINK = re.compile(r'''pants\(['"]([^)]+)['"]\)(#.*)?''')

  def process_md(self, output_path, source, fragmented, url_builder, css=None):
    def parse_url(spec):
      match = self.PANTS_LINK.match(spec)
      if match:
        address = Address.parse(match.group(1), relative_to=get_buildroot())
        page = self.context.build_graph.get_target(address)
        anchor = match.group(2) or ''
        if not page:
          raise TaskError('Invalid markdown link to pants target: "{}". '.format(match.group(1)) +
                          'Is your page missing a dependency on this target?')
        alias, url = url_builder(page)
        return alias, url + anchor
      else:
        return spec, spec

    def build_url(label):
      components = label.split('|', 1)
      if len(components) == 1:
        return parse_url(label.strip())
      else:
        alias, link = components
        _, url = parse_url(link.strip())
        return alias, url

    wikilinks = WikilinksExtension(build_url)

    safe_mkdir(os.path.dirname(output_path))
    with codecs.open(output_path, 'w', 'utf-8') as output:
      source_path = os.path.join(get_buildroot(), source)
      with codecs.open(source_path, 'r', 'utf-8') as source_stream:
        md_html = markdown.markdown(
          source_stream.read(),
          extensions=['codehilite(guess_lang=False)',
                      'extra',
                      'tables',
                      'toc',
                      wikilinks,
                      IncludeExcerptExtension(source_path)],
        )
        if fragmented:
          style_css = (HtmlFormatter(style=self.code_style)).get_style_defs('.codehilite')
          template = resource_string(__name__,
                                     os.path.join(self._templates_dir, 'fragment.mustache'))
          generator = Generator(template, style_css=style_css, md_html=md_html)
          generator.write(output)
        else:
          style_link = os.path.relpath(css, os.path.dirname(output_path))
          template = resource_string(__name__, os.path.join(self._templates_dir, 'page.mustache'))
          generator = Generator(template, style_link=style_link, md_html=md_html)
          generator.write(output)
        return output.name

  def process_rst(self, workunit, page, output_path, source, fragmented):
    source_path = os.path.join(get_buildroot(), source)
    with codecs.open(source_path, 'r', 'utf-8') as source_stream:
      rst_html, returncode = rst_to_html(source_stream.read(), stderr=workunit.output('stderr'))
      if returncode != 0:
        message = '{} rendered with errors.'.format(source_path)
        if self.get_options().ignore_failure:
          self.context.log.warn(message)
        else:
          raise TaskError(message, exit_code=returncode, failed_targets=[page])

      template_path = os.path.join(self._templates_dir,
                                   'fragment.mustache' if fragmented else 'page.mustache')
      template = resource_string(__name__, template_path)
      generator = Generator(template, md_html=rst_html)
      safe_mkdir(os.path.dirname(output_path))
      with codecs.open(output_path, 'w', 'utf-8') as output:
        generator.write(output)
        return output.name
