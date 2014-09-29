# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import codecs
import os
import re

import markdown
from pkg_resources import resource_string
from pygments.formatters.html import HtmlFormatter
from pygments.styles import get_all_styles

from pants import binary_util
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.generator import Generator
from pants.backend.core.targets.doc import Page
from pants.backend.core.tasks.task import Task
from pants.util.dirutil import safe_mkdir, safe_open


def configure_codehighlight_options(option_group, mkflag):
  all_styles = list(get_all_styles())
  option_group.add_option(mkflag('code-style'), dest='markdown_to_html_code_style',
                          type='choice', choices=all_styles,
                          help='Selects the stylesheet to use for code highlights, one of: '
                               '%s.' % ' '.join(all_styles))

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


def choose_include_lines(s, params, source_path):
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
    return []
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
      return []
  return chosen_lines


class IncludeExcerptPattern(markdown.inlinepatterns.Pattern):
  def __init__(self, md=None, source_path=None):
    '''
    :param source_path: path to source .md file.
    '''
    markdown.inlinepatterns.Pattern.__init__(self, INCLUDE_PATTERN)
    self.source_path = source_path

  def handleMatch(self, match):
    params = match.group('params') or ''
    rel_include_path = match.group('path')
    source_dir = os.path.dirname(self.source_path)
    include_path = os.path.join(source_dir, rel_include_path)
    try:
      with open(include_path) as include_file:
        include_text = include_file.read()
    except IOError as e:
      raise IOError('Markdown file {0} tried to include file {1}, got '
                    '{2}'.format(self.source_path,
                                 rel_include_path,
                                 e.strerror))
    include_lines = choose_include_lines(include_text, params, self.source_path)
    if not include_lines:
      raise TaskError('Markdown file {0} tried to include file {1} but '
                      'filtered out everything'.format(self.source_path,
                                                       rel_include_path))
    el = markdown.util.etree.Element('pre')
    el.text = markdown.util.AtomicString('\n'.join(include_lines))
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
  "Given a page target, return partial path for an output .html"
  source_path = page.sources_relative_to_buildroot()[0]
  return os.path.splitext(source_path)[0] + ".html"


class MarkdownToHtml(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    configure_codehighlight_options(option_group, mkflag)

    option_group.add_option(mkflag('open'), mkflag('open', negate=True),
                            dest='markdown_to_html_open',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%default] Open the generated documents in a browser.')

    option_group.add_option(mkflag('fragment'), mkflag('fragment', negate=True),
                            dest = 'markdown_to_html_fragment',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%default] Generate a fragment of html to embed in a page.')

    option_group.add_option(mkflag('extension'), dest='markdown_to_html_extensions',
                            action='append',

                            help='Override the default markdown extensions and process pages '
                                 'whose source have these extensions instead.')

  @classmethod
  def product_types(cls):
    return ['markdown_html', 'wiki_html']

  def __init__(self, *args, **kwargs):
    super(MarkdownToHtml, self).__init__(*args, **kwargs)

    # TODO(pl): None of this should be setup in the __init__, it can interfere with unrelated
    # tasks if this Task is misconfigured.
    self._templates_dir = os.path.join('templates', 'markdown')
    self.open = self.context.options.markdown_to_html_open

    self.extensions = set(
      self.context.options.markdown_to_html_extensions or
      self.context.config.getlist('markdown-to-html',
                                  'extensions',
                                  default=['.md', '.markdown'])
    )

    self.fragment = self.context.options.markdown_to_html_fragment

    self.code_style = self.context.config.get('markdown-to-html', 'code-style', default='friendly')
    if hasattr(self.context.options, 'markdown_to_html_code_style'):
      if self.context.options.markdown_to_html_code_style:
        self.code_style = self.context.options.markdown_to_html_code_style

  def execute(self):
    # TODO(John Sirois): consider adding change detection

    outdir = os.path.join(self.context.config.getdefault('pants_distdir'), 'markdown')
    css_path = os.path.join(outdir, 'css', 'codehighlight.css')
    css = emit_codehighlight_css(css_path, self.code_style)
    if css:
      self.context.log.info('Emitted %s' % css)

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

    plaingenmap = self.context.products.get('markdown_html')
    wikigenmap = self.context.products.get('wiki_html')
    show = []
    for page in self.context.targets(is_page):
      _, ext = os.path.splitext(page.source)
      if ext in self.extensions:
        def process_page(key, outdir, url_builder, config, genmap, fragment=False):
          html_path = self.process(
            os.path.join(outdir, page_to_html_path(page)),
            os.path.join(page.payload.sources.rel_path, page.source),
            self.fragment or fragment,
            url_builder,
            config,
            css=css
          )
          self.context.log.info('Processed %s to %s' % (page.source, html_path))
          relpath = os.path.relpath(html_path, outdir)
          genmap.add(key, outdir, [relpath])
          return html_path

        def url_builder(linked_page, config=None):
          dest = page_to_html_path(linked_page)
          src_dir = os.path.dirname(page_to_html_path(page))
          return linked_page.name, os.path.relpath(dest, src_dir)

        page_path = os.path.join(outdir, 'html')
        html = process_page(page, page_path, url_builder, lambda p: None, plaingenmap)
        if css and not self.fragment:
          plaingenmap.add(page, self.workdir, list(css_path))
        if self.open and page in roots:
          show.append(html)

        if page.provides:
          for wiki in page.provides:
            def get_config(page):
              # Take the first provided WikiArtifact. If a page is published to multiple places, it's
              # undefined what the "proper" one is to link to. So we just take whatever is "first".
              for wiki_artifact in page.payload.provides:
                return wiki_artifact.config
            basedir = os.path.join(self.workdir, str(hash(wiki)))
            process_page((wiki, page), basedir, wiki.wiki.url_builder, get_config,
                         wikigenmap, fragment=True)

    if show:
      binary_util.ui_open(*show)

  PANTS_LINK = re.compile(r'''pants\(['"]([^)]+)['"]\)(#.*)?''')

  def process(self, output_path, source, fragmented, url_builder, get_config, css=None):
    def parse_url(spec):
      match = MarkdownToHtml.PANTS_LINK.match(spec)
      if match:
        address = SyntheticAddress.parse(match.group(1), relative_to=get_buildroot())
        page = self.context.build_graph.get_target(address)
        anchor = match.group(2) or ''
        if not page:
          raise TaskError('Invalid markdown link to pants target: "%s". ' % match.group(1) +
                          'Is your page missing a dependency on this target?')
        alias, url = url_builder(page, config=get_config(page))
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
      with codecs.open(source_path, 'r', 'utf-8') as input:
        md_html = markdown.markdown(
          input.read(),
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
                                     os.path.join(self._templates_dir,
                                                  'fragment.mustache'))
          generator = Generator(template,
                                style_css=style_css,
                                md_html=md_html)
          generator.write(output)
        else:
          style_link = os.path.relpath(css, os.path.dirname(output_path))
          template = resource_string(__name__, os.path.join(self._templates_dir, 'page.mustache'))
          generator = Generator(template,
                                style_link=style_link,
                                md_html=md_html)
          generator.write(output)
        return output.name
