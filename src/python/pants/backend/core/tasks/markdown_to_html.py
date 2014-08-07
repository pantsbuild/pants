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


def id_to_html_path(id):
  "Given a target id, give a nice path for an output .html path"
  # _ prefix is because //readme gets an id .readme: whoops, hidden file
  return "_" + str(id) + ".html"


class MarkdownToHtml(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    configure_codehighlight_options(option_group, mkflag)

    option_group.add_option(mkflag('open'), mkflag('open', negate=True),
                            dest = 'markdown_to_html_open',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help = '[%default] Open the generated documents in a browser.')

    option_group.add_option(mkflag('fragment'), mkflag('fragment', negate=True),
                            dest = 'markdown_to_html_fragment',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help = '[%default] Generate a fragment of html to embed in a page.')

    option_group.add_option(mkflag('extension'), dest = 'markdown_to_html_extensions',
                            action='append',
                            help = 'Override the default markdown extensions and process pages '
                                   'whose source have these extensions instead.')

  @classmethod
  def product_types(cls):
    return ['markdown_html', 'wiki_html']

  def __init__(self, *args, **kwargs):
    super(MarkdownToHtml, self).__init__(*args, **kwargs)

    self._templates_dir = os.path.join('templates', 'markdown')
    self.open = self.context.options.markdown_to_html_open

    self.extensions = set(
      self.context.options.markdown_to_html_extensions
      or self.context.config.getlist('markdown-to-html', 'extensions', default=['.md', '.markdown'])
    )

    self.fragment = self.context.options.markdown_to_html_fragment

    self.code_style = self.context.config.get('markdown-to-html', 'code-style', default='friendly')
    if hasattr(self.context.options, 'markdown_to_html_code_style'):
      if self.context.options.markdown_to_html_code_style:
        self.code_style = self.context.options.markdown_to_html_code_style

  def execute(self):
    # TODO(John Sirois): consider adding change detection

    css_relpath = os.path.join('css', 'codehighlight.css')
    css = emit_codehighlight_css(os.path.join(self.workdir, css_relpath), self.code_style)
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
            outdir,
            os.path.join(page.payload.sources_rel_path, page.source),
            self.fragment or fragment,
            url_builder,
            config,
            page.identifier,
            css=css
          )
          self.context.log.info('Processed %s to %s' % (page.source, html_path))
          relpath = os.path.relpath(html_path, outdir)
          genmap.add(key, outdir, [relpath])
          return html_path

        def url_builder(linked_page, config=None):
          dest = id_to_html_path(linked_page.identifier)
          src_dir = os.path.dirname(id_to_html_path(page.identifier))
          return linked_page.name, os.path.relpath(dest, src_dir)

        page_path = os.path.join(self.workdir, 'html')
        html = process_page(page, page_path, url_builder, lambda p: None, plaingenmap)
        if css and not self.fragment:
          plaingenmap.add(page, self.workdir, list(css_relpath))
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

  def process(self, outdir, source, fragmented, url_builder, get_config, targid, css=None):
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

    output_path = os.path.join(outdir, id_to_html_path(targid))
    safe_mkdir(os.path.dirname(output_path))
    with codecs.open(output_path, 'w', 'utf-8') as output:
      with codecs.open(os.path.join(get_buildroot(), source), 'r', 'utf-8') as input:
        md_html = markdown.markdown(
          input.read(),
          extensions=['codehilite(guess_lang=False)', 'extra', 'tables', 'toc', wikilinks],
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
