# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import codecs
import os
import re

from pkg_resources import resource_string
from pygments.formatters.html import HtmlFormatter
from pygments.styles import get_all_styles

from pants.backend.core.targets.doc import Page
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.generator import Generator
from pants.base.workunit import WorkUnitLabel
from pants.binaries import binary_util
from pants.build_graph.address import Address
from pants.task.task import Task
from pants.util.dirutil import safe_mkdir


def util():
  """Indirection function so we can lazy-import our utils.

  It's an expensive import that invokes re.compile a lot (via markdown and pygments),
  so we don't want to incur that cost unless we must.
  """
  from pants.backend.core.tasks import markdown_to_html_utils
  return markdown_to_html_utils


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
    css = util().emit_codehighlight_css(css_path, self.code_style)
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
                os.path.join(outdir, util().page_to_html_path(page)),
                os.path.join(page.payload.sources.rel_path, page.source),
                self.fragment or fragment,
              )
          else:
            with self.context.new_workunit(name='md'):
              html_path = self.process_md(
                os.path.join(outdir, util().page_to_html_path(page)),
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
          dest = util().page_to_html_path(linked_page)
          src_dir = os.path.dirname(util().page_to_html_path(page))
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

    wikilinks = util().WikilinksExtension(build_url)

    safe_mkdir(os.path.dirname(output_path))
    with codecs.open(output_path, 'w', 'utf-8') as output:
      source_path = os.path.join(get_buildroot(), source)
      with codecs.open(source_path, 'r', 'utf-8') as source_stream:
        md_html = util().markdown.markdown(
          source_stream.read(),
          extensions=['codehilite(guess_lang=False)',
                      'extra',
                      'tables',
                      'toc',
                      wikilinks,
                      util().IncludeExcerptExtension(source_path)],
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
      rst_html, returncode = util().rst_to_html(source_stream.read(),
                                                stderr=workunit.output('stderr'))
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
