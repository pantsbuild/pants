# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import collections
import json
import os
import re
import shutil
from builtins import object, open, range
from datetime import datetime

from pystache import Renderer

from pants.backend.docgen.tasks.generate_pants_reference import GeneratePantsReference
from pants.backend.docgen.tasks.markdown_to_html import MarkdownToHtml
from pants.base.exceptions import TaskError
from pants.task.task import Task


"""Static Site Generator for the Pants Build documentation site.

Suggested use:
  cd pants
  ./build-support/bin/publish_docs.sh  # invokes sitegen.py
"""


def beautiful_soup(*args, **kwargs):
  """Indirection function so we can lazy-import bs4.

  It's an expensive import that invokes re.compile a lot, so we don't want to incur that cost
  unless we must.
  """
  import bs4
  return bs4.BeautifulSoup(*args, **kwargs)


class SiteGen(Task):
  """Generate the Pants static web site."""

  @classmethod
  def register_options(cls, register):
    super(SiteGen, cls).register_options(register)
    register('--config-path', type=list, help='Path to .json file describing site structure.')

  # TODO: requiring these products ensures that the markdown and reference tasks run before this
  # one, but we don't use those products.
  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require(MarkdownToHtml.MARKDOWN_HTML_PRODUCT)
    round_manager.require_data(GeneratePantsReference.PANTS_REFERENCE_PRODUCT)
    round_manager.require_data(GeneratePantsReference.BUILD_DICTIONARY_PRODUCT)

  def execute(self):
    if not self.get_options().config_path:
      raise TaskError('The config_path option must be specified, e.g., with the --config-path flag')
    for config_path in self.get_options().config_path:
      config = load_config(config_path)
      soups = load_soups(config)
      precomputed = precompute(config, soups)
      transform_soups(config, soups, precomputed)
      template = load_template(config)
      write_en_pages(config, soups, precomputed, template)
      copy_extras(config)


def load_config(json_path):
  """Load config info from a .json file and return it."""
  with open(json_path, 'r') as json_file:
    config = json.loads(json_file.read())
  # sanity-test the config:
  assert(config['tree'][0]['page'] == 'index')
  return config


def load_soups(config):
  """Generate BeautifulSoup AST for each page listed in config."""
  soups = {}
  for page, path in config['sources'].items():
    with open(path, 'r') as orig_file:
      soups[page] = beautiful_soup(orig_file.read(), features='html.parser')
  return soups


class Precomputed(object):
  """Info we compute (and preserve) before we mutate things."""

  def __init__(self, page, pantsref):
    """
    :param page: dictionary of per-page precomputed info
    :param pantsref: dictionary of pantsrefs {'foo': 'path/to/page.html#fooref', ...}
    """
    self.page = page
    self.pantsref = pantsref


class PrecomputedPageInfo(object):
  """Info we compute (and preserve) for each page before we mutate things."""

  def __init__(self, title, show_toc):
    """
    :param title: Page title
    :param show_toc: True iff we should show a toc for this page.
    """
    self.title = title
    self.show_toc = show_toc
    self.toc = []


def precompute_pantsrefs(soups):
  """Return links for <a pantsmark="foo"> tags. Mutates soups to give needed ids.

  If we see <a pantsref="foo">something</a>, that's a link whose destination is
  a <a pantsmark="foo"> </a> tag, perhaps on some other tag. To stitch these
  together, we scan the docset to find all the pantsmarks. If an pantsmark does not
  yet have an id to anchor, we give it one.

  Return value dictionary maps pantsrefs to locations:
  { "foo": "path/to/foo.html#fooref", "bar": "other/page.html#barref", ...}
  """
  accumulator = {}
  for (page, soup) in soups.items():
    existing_anchors = find_existing_anchors(soup)
    count = 100
    for tag in soup.find_all('a'):
      if not tag.has_attr('pantsmark'):
        continue
      pantsmark = tag['pantsmark']
      if pantsmark in accumulator:
        raise TaskError('pantsmarks are unique but "{}" appears in {} and {}'
                        .format(pantsmark, page, accumulator[pantsmark]))

      # To link to a place "mid-page", we need an HTML anchor.
      # If this tag already has such an anchor, use it.
      # Else, make one up.
      anchor = tag.get('id') or tag.get('name')
      if not anchor:
        anchor = pantsmark
        while anchor in existing_anchors:
          count += 1
          anchor = '{}_{}'.format(pantsmark, count)
        tag['id'] = anchor
        existing_anchors = find_existing_anchors(soup)

      link = '{}.html#{}'.format(page, anchor)
      accumulator[pantsmark] = link
  return accumulator


def precompute(config, soups):
  """Return info we want to compute (and preserve) before we mutate things."""
  show_toc = config.get('show_toc', {})
  page = {}
  pantsrefs = precompute_pantsrefs(soups)
  for p, soup in soups.items():
    title = get_title(soup) or p
    page[p] = PrecomputedPageInfo(title=title, show_toc=show_toc.get(p, True))
  return Precomputed(page=page, pantsref=pantsrefs)


def fixup_internal_links(config, soups):
  """Find href="..." links that link to pages in our docset; fix them up.

  We don't preserve relative paths between files as we copy-transform them
  from source to dest. So adjust the paths to work with new locations.
  """
  # Pages can come from different dirs; they can go to different dirs.
  # Thus, there's some relative-path-computing here.
  reverse_directory = {}
  for d, s in config['sources'].items():
    reverse_directory[s] = d
  for name, soup in soups.items():
    old_src_dir = os.path.dirname(config['sources'][name])
    for tag in soup.find_all(True):
      if not 'href' in tag.attrs:
        continue
      old_rel_path = tag['href'].split('#')[0]
      old_dst = os.path.normpath(os.path.join(old_src_dir, old_rel_path))
      if not old_dst in reverse_directory:
        continue
      new_dst = reverse_directory[old_dst] + '.html'
      new_rel_path = rel_href(name, new_dst)
      # string replace instead of assign to not loose anchor in foo.html#anchor
      tag['href'] = tag['href'].replace(old_rel_path, new_rel_path, 1)


_heading_re = re.compile(r'^h[1-6]$')  # match heading tag names h1,h2,h3,...


def rel_href(src, dst):
  """For src='foo/bar.html', dst='garply.html#frotz' return relative link '../garply.html#frotz'.
  """
  src_dir = os.path.dirname(src)
  return os.path.relpath(dst, src_dir)


def find_existing_anchors(soup):
  """Return existing ids (and names) from a soup."""
  existing_anchors = set()
  for tag in soup.find_all(True):
    for attr in ['id', 'name']:
      if tag.has_attr(attr):
        existing_anchors.add(tag.get(attr))
  return existing_anchors


def ensure_headings_linkable(soups):
  """foreach soup, foreach h1,h2,etc, if no id=... or name=..., give it one.

  Enables tables of contents.
  """
  for soup in soups.values():
    ensure_page_headings_linkable(soup)


def ensure_page_headings_linkable(soup):
  # To avoid re-assigning an existing id, note 'em down.
  # Case-insensitve because distinguishing links #Foo and #foo would be weird.
  existing_anchors = find_existing_anchors(soup)
  count = 100
  for tag in soup.find_all(_heading_re):
    if not (tag.has_attr('id') or tag.has_attr('name')):
      snippet = ''.join([c for c in tag.text if c.isalpha()])[:20]
      while True:
        count += 1
        candidate_id = 'heading_{}_{}'.format(snippet, count).lower()
        if not candidate_id in existing_anchors:
          existing_anchors.add(candidate_id)
          tag['id'] = candidate_id
          break


def link_pantsrefs(soups, precomputed):
  """Transorm soups: <a pantsref="foo"> becomes <a href="../foo_page.html#foo">"""
  for (page, soup) in soups.items():
    for a in soup.find_all('a'):
      if not a.has_attr('pantsref'):
        continue
      pantsref = a['pantsref']
      if not pantsref in precomputed.pantsref:
        raise TaskError('Page {} has pantsref "{}" and I cannot find pantsmark for'
                        ' it'.format(page, pantsref))
      a['href'] = rel_href(page, precomputed.pantsref[pantsref])


def transform_soups(config, soups, precomputed):
  """Mutate our soups to be better when we write them out later."""
  fixup_internal_links(config, soups)
  ensure_headings_linkable(soups)

  # Do this after ensure_headings_linkable so that there will be links.
  generate_page_tocs(soups, precomputed)
  link_pantsrefs(soups, precomputed)


def get_title(soup):
  """Given a soup, pick out a title"""
  if soup.title:
    return soup.title.string
  if soup.h1:
    return soup.h1.string
  return ''


def generate_site_toc(config, precomputed, here):
  site_toc = []

  def recurse(tree, depth_so_far):
    for node in tree:
      if 'collapsible_heading' in node and 'pages' in node:
        heading = node['collapsible_heading']
        pages = node['pages']
        links = []
        collapse_open = False
        for cur_page in pages:
          html_filename = '{}.html'.format(cur_page)
          page_is_here = cur_page == here
          if page_is_here:
            link = html_filename
            collapse_open = True
          else:
            link = os.path.relpath(html_filename, os.path.dirname(here))
          links.append(dict(link=link, text=precomputed.page[cur_page].title, here=page_is_here))
        site_toc.append(dict(depth=depth_so_far, links=links, dropdown=True, heading=heading, id=heading.replace(' ', '-'), open=collapse_open))
      if 'heading' in node:
        heading = node['heading']
        site_toc.append(dict(depth=depth_so_far, links=None, dropdown=False, heading=heading, id=heading.replace(' ', '-')))
      if 'pages' in node and not 'collapsible_heading' in node:
        pages = node['pages']
        links = []
        for cur_page in pages:
          html_filename = '{}.html'.format(cur_page)
          page_is_here = cur_page == here
          if page_is_here:
            link = html_filename
          else:
            link = os.path.relpath(html_filename, os.path.dirname(here))
          links.append(dict(link=link, text=precomputed.page[cur_page].title, here=page_is_here))
        site_toc.append(dict(depth=depth_so_far, links=links, dropdown=False, heading=None, id=heading.replace(' ', '-')))
      if 'children' in node:
        recurse(node['children'], depth_so_far + 1)
  if 'tree' in config:
    recurse(config['tree'], 0)
  return site_toc


def hdepth(tag):
  """Compute an h tag's "outline depth".

  E.g., h1 at top level is 1, h1 in a section is 2, h2 at top level is 2.
  """
  if not _heading_re.search(tag.name):
    raise TaskError("Can't compute heading depth of non-heading {}".format(tag))
  depth = int(tag.name[1], 10)  # get the 2 from 'h2'
  cursor = tag
  while cursor:
    if cursor.name == 'section':
      depth += 1
    cursor = cursor.parent
  return depth


def generate_page_tocs(soups, precomputed):
  for name, soup in soups.items():
    if precomputed.page[name].show_toc:
      precomputed.page[name].toc = generate_page_toc(soup)


def generate_page_toc(soup):
  """Return page-level (~list of headings) TOC template data for soup"""
  # Maybe we don't want to show all the headings. E.g., it's common for a page
  # to have just one H1, a title at the top. Our heuristic: if a page has just
  # one heading of some outline level, don't show it.
  found_depth_counts = collections.defaultdict(int)
  for tag in soup.find_all(_heading_re):
    if (tag.get('id') or tag.get('name')):
      found_depth_counts[hdepth(tag)] += 1

  depth_list = [i for i in range(100) if 1 < found_depth_counts[i]]
  depth_list = depth_list[:4]
  toc = []
  for tag in soup.find_all(_heading_re):
    depth = hdepth(tag)
    if depth in depth_list:
      toc.append(dict(depth=depth_list.index(depth) + 1,
                      link=tag.get('id') or tag.get('name'),
                      text=tag.text))
  return toc


def generate_generated(config, here):
  return '{} {}'.format(config['sources'][here], datetime.now().isoformat())


def render_html(dst, config, soups, precomputed, template):
  soup = soups[dst]
  renderer = Renderer()
  title = precomputed.page[dst].title
  topdots = '../' * dst.count('/')
  body_html = '{}'.format(soup.body) if soup.body else '{}'.format(soup)
  html = renderer.render(template,
                         body_html=body_html,
                         generated=generate_generated(config, dst),
                         site_toc=generate_site_toc(config, precomputed, dst),
                         has_page_toc=bool(precomputed.page[dst].toc),
                         page_path=dst,
                         page_toc=precomputed.page[dst].toc,
                         title=title,
                         topdots=topdots)
  return html


def write_en_pages(config, soups, precomputed, template):
  outdir = config['outdir']
  for dst in soups:
    html = render_html(dst, config, soups, precomputed, template)
    dst_path = os.path.join(outdir, dst + '.html')
    dst_dir = os.path.dirname(dst_path)
    if not os.path.isdir(dst_dir):
      os.makedirs(dst_dir)
    with open(dst_path, 'w') as f:
      f.write(html)


def copy_extras(config):
  """copy over "extra" files named in config json: stylesheets, logos, ..."""
  outdir = config['outdir']
  for dst, src in config['extras'].items():
    dst_path = os.path.join(outdir, dst)
    dst_dir = os.path.dirname(dst_path)
    if not os.path.isdir(dst_dir):
      os.makedirs(dst_dir)
    shutil.copy(src, dst_path)


def load_template(config):
  """Return text of template file specified in config"""
  with open(config['template'], 'r') as template_file:
    return template_file.read()
