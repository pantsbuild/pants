# ==================================================================================================
# Copyright 2012 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

__author__ = 'John Sirois'

try:
  import markdown

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

  HAS_MARKDOWN = True
except ImportError:
  HAS_MARKDOWN = False

try:
  from pygments.formatters.html import HtmlFormatter
  from pygments.styles import get_all_styles

  def configure_codehighlight_options(option_group, mkflag):
    all_styles = list(get_all_styles())
    option_group.add_option(mkflag("code-style"), dest="markdown_to_html_code_style",
                            type="choice", choices=all_styles,
                            help="Selects the stylesheet to use for code highlights, one of: "
                                 "%s." % ' '.join(all_styles))

  def emit_codehighlight_css(path, style):
    with safe_open(path, 'w') as css:
      css.write((HtmlFormatter(style=style)).get_style_defs('.codehilite'))
    return path
except ImportError:
  def configure_codehighlight_options(option_group, mkflag): pass
  def emit_codehighlight_css(path, style): pass


import os
import re
import textwrap

from twitter.common.dirutil import safe_open

from twitter.pants import binary_util, get_buildroot
from twitter.pants.base import Address, Target
from twitter.pants.targets import Page
from twitter.pants.tasks import Task, TaskError

class MarkdownToHtml(Task):
  AVAILABLE = HAS_MARKDOWN

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    configure_codehighlight_options(option_group, mkflag)

    option_group.add_option(mkflag("open"), mkflag("open", negate=True),
                            dest = "markdown_to_html_open",
                            action="callback", callback=mkflag.set_bool, default=False,
                            help = "[%default] Open the generated documents in a browser.")

    option_group.add_option(mkflag("standalone"), mkflag("standalone", negate=True),
                            dest = "markdown_to_html_standalone",
                            action="callback", callback=mkflag.set_bool, default=False,
                            help = "[%default] Generate a well-formed standalone html document.")

    option_group.add_option(mkflag("outdir"), dest="markdown_to_html_outdir",
                            help="Emit generated html in to this directory.")

    option_group.add_option(mkflag("extension"), dest = "markdown_to_html_extensions",
                            action="append",
                            help = "Override the default markdown extensions and process pages "
                                   "whose source have these extensions instead.")

  def __init__(self, context):
    Task.__init__(self, context)

    self.open = context.options.markdown_to_html_open

    pants_workdir = context.config.getdefault('pants_workdir')
    self.outdir = (
      context.options.markdown_to_html_outdir
      or context.config.get('markdown-to-html',
                            'workdir',
                            default=os.path.join(pants_workdir, 'markdown'))
    )

    self.extensions = set(
      context.options.markdown_to_html_extensions
      or context.config.getlist('markdown-to-html', 'extensions', default=['.md', '.markdown'])
    )

    self.standalone = context.options.markdown_to_html_standalone

    self.code_style = context.config.get('markdown-to-html', 'code-style', default='friendly')
    if hasattr(context.options, 'markdown_to_html_code_style'):
      if context.options.markdown_to_html_code_style:
        self.code_style = context.options.markdown_to_html_code_style

  def execute(self, targets):
    if not MarkdownToHtml.AVAILABLE:
      raise TaskError('Cannot process markdown - no markdown lib on the sys.path')

    # TODO(John Sirois): consider adding change detection

    css_relpath = os.path.join('css', 'codehighlight.css')
    css = emit_codehighlight_css(os.path.join(self.outdir, css_relpath), self.code_style)
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

    genmap = self.context.products.get('markdown_html')
    show = []
    for page in filter(is_page, targets):
      _, ext = os.path.splitext(page.source)
      if ext in self.extensions:
        def process_page(key, outdir, url_builder, config):
          outputs = list()
          if css and self.standalone:
            outputs.append(css_relpath)
          html_path = self.process(
            outdir,
            page.target_base,
            page.source,
            self.standalone,
            url_builder,
            config,
            css=css
          )
          self.context.log.info('Processed %s to %s' % (page.source, html_path))
          outputs.append(os.path.relpath(html_path, outdir))
          genmap.add(key, outdir, outputs)
          return html_path

        def url_builder(linked_page, config=None):
          path, ext = os.path.splitext(linked_page.source)
          return linked_page.name, os.path.relpath(path + '.html', os.path.dirname(page.source))

        html = process_page(page, os.path.join(self.outdir, 'html'), url_builder, lambda p: None)
        if self.open and page in roots:
          show.append(html)

        for wiki in page.wikis():
          def get_config(page):
            return page.wiki_config(wiki)
          basedir = os.path.join(self.outdir, wiki.id)
          process_page((wiki, page), basedir, wiki.url_builder, get_config)

    if show:
      binary_util.ui_open(*show)

  PANTS_LINK = re.compile(r'''pants\(['"]([^)]+)['"]\)''')

  def process(self, outdir, base, source, standalone, url_builder, get_config, css=None):
    def parse_url(spec):
      match = MarkdownToHtml.PANTS_LINK.match(spec)
      if match:
        page = Target.get(Address.parse(get_buildroot(), match.group(1)))
        if not page:
          raise TaskError('Invalid link %s' % match.group(1))
        alias, url = url_builder(page, config=get_config(page))
        return alias, url
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

    path, ext = os.path.splitext(source)
    with safe_open(os.path.join(outdir, path + '.html'), 'w') as output:
      with open(os.path.join(get_buildroot(), base, source), 'r') as input:
        md_html = markdown.markdown(
          input.read(),
          extensions=['codehilite(guess_lang=False)', 'extra', 'tables', 'toc', wikilinks],
        )
        if standalone:
          if css:
            css_relpath = os.path.relpath(css, outdir)
            out_relpath = os.path.dirname(source)
            link_relpath = os.path.relpath(css_relpath, out_relpath)
            css = '<link rel="stylesheet" type="text/css" href="%s"/>' % link_relpath
          html = textwrap.dedent('''
          <html>
            <head>
              %s
            </head>
            <body>
          <!-- generated by pants! -->
          %s
            </body>
          </html>
          ''').strip() % (css or '', md_html)
          output.write(html)
        else:
          if css:
            with safe_open(css) as fd:
              output.write(textwrap.dedent('''
              <style type="text/css">
              %s
              </style>
              ''').strip() % fd.read())
              output.write('\n')
          output.write(md_html)
        return output.name
