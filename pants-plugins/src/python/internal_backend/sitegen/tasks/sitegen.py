# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
import json
import os
import re
import shutil
from datetime import datetime

from pystache import Renderer
from six.moves import range

from pants.backend.docgen.tasks.generate_pants_reference import GeneratePantsReference
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.engine.rules import rule
from pants.engine.selectors import Select
from pants.task.task import Task
from pants.util.dirutil import read_file
from pants.util.objects import datatype


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


class MarkdownPageExport(datatype('MarkdownPageExport', [
    'rel_path',
    'page_name',
    'show_toc',
])): pass


def _make_page_export(abs_html_path, show_toc, buildroot):
    rel_html_path = os.path.relpath(abs_html_path, buildroot)
    html_filename = os.path.basename(rel_html_path)
    page_name = os.path.splitext(html_filename)[0]
    return MarkdownPageExport(
      rel_path=rel_html_path,
      page_name=page_name,
      show_toc=show_toc)


class SoupedPage(datatype('SoupedPage', [
    'title',
    'soup',
    'md_page_export',
])): pass


@rule(SoupedPage, [Select(MarkdownPageExport)])
def soupify(md_page_export):
  file_path = md_page_export.rel_path
  with open(file_path, 'rb') as orig_file:
    file_contents = orig_file.read().decode('utf-8')
    soup = beautiful_soup(file_contents)
    title = get_title(soup) or md_page_export.page_name
    return SoupedPage(title=title, soup=soup, md_page_export=md_page_export)


class PantsMark(datatype('PantsMark', [
    'mark_name',
    'souped_page',
    'mark_element_id',
])): pass


class PantsRef(datatype('PantsRef', [
    'ref_mark_name',
    'ref_element',
])): pass


def _ensure_element_id(soup, element, id_base):
  """Mutates the element by setting an id attribute if necessary to ensure the
  returned id is valid."""
  cur_id = element.get('id')
  if cur_id:
    return cur_id

  # TODO: there's probably a better way to generate unique ids...
  cur_id = id_base
  uniq_count = 1
  while soup.find(id=cur_id):
    cur_id = '{}_{}'.format(id_base, str(uniq_count))
    uniq_count += 1

  element['id'] = cur_id
  return cur_id


# TODO: see src/docs/docsite.html.mustache for what we need to pass to the
# render() function of pystache (which i think should be done in this class too)
class PantsReferenceLinker(object):
  def __init__(self):
    # mark_name ->
    self._mark_dict = {}
    self._processed_pages = []

  def _accept_mark(self, souped_page, elem):
    mark_name = elem['pantsmark']
    mark_element_id = _ensure_element_id(soup, elem, mark_name)
    pants_mark = PantsMark(mark_name, souped_page, mark_element_id)
    # TODO: ???

  def _accept_ref(self, souped_page, elem):
    ref_mark_name = elem['pantsref']
    pants_ref = PantsRef(ref_mark_name, elem)
    # TODO: ???

  def accept_page(self, souped_page):
    """Extract 'pantsmark' and 'pantsref' locations from the page.

    NB: May modify the page content to ensure elements with the 'pantsmark'
    attribute have a unique id that can be linked to from other pages. Think of
    this like rust ownership. Use `get_result()` to get page objects to write to
    file, etc.
    """
    refs = []
    marks = []
    soup = souped_page.soup
    for elem in soup.find_all(True):
      if elem.has_attr('pantsmark'):
        self._accept_mark(souped_page, elem)
      if elem.has_attr('pantsref'):
        self._accept_ref(souped_page, elem)
    # TODO: toc stuff (our markdown generation uses the 'toc' extension -- what
    # does this do and can we use it instead of doing our own stuff manually?)

  def get_result(self):
    # TODO: return modified pages, signal e.g. multiple pantsmarks of the same
    # name, ensure all pantsrefs match to a pantsmark, apply toc


def _extract_refs_marks(souped_page):
  refs = []
  marks = []
  soup = souped_page.soup
  for elem in soup.find_all(True):
    if elem.has_attr('pantsmark'):
      mark_name = elem['pantsmark']
      mark_element_id = _generate_insert_element_id(soup, elem, mark_name)
      pants_mark = PantsMark(mark_name, souped_page, mark_element_id)
      marks.append(pants_mark)
    if elem.has_attr('pantsref'):
      ref_mark_name = elem['pantsref']
      pants_ref = PantsRef(ref_mark_name, elem)
      refs.append(pants_ref)

  return (refs, marks)


def render_souped(souped, template, renderer):
  soup = souped.soup
  export = souped.md_page_export
  to_render = soup.body or soup
  timestamp = datetime.now().isoformat()
  return renderer.render(
    template,
    body_html=str(to_render),
    generated='{} {}'.format(export.rel_path, timestamp),
    site_toc=None,
    has_page_toc=export.show_toc,
    page_path=export.rel_path)


class ProductiveSiteGen(Task):

  PANTS_DOCSITE_HTML_TEMPLATE_PATH = 'src/docs/docsite.html.mustache'

  PANTS_DOCSITE_OUTDIR = 'dist/docsite'

  @classmethod
  def register_options(cls, register):
    super(ProductiveSiteGen, cls).register_options(register)

    register('--template-path', type=str, advanced=True,
             default=cls.PANTS_DOCSITE_HTML_TEMPLATE_PATH,
             help='Path to a mustache template file to use for '
                  'generating the site.')
    register('--outdir', type=str, advanced=True,
             default=cls.PANTS_DOCSITE_OUTDIR,
             help='Path to a directory to render the generated site in.')

  @memoized_property
  def template(self):
    return read_file(self.context.options.template_path)

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require('markdown_html')
    round_manager.require_data(GeneratePantsReference.PANTS_REFERENCE_PRODUCT)
    round_manager.require_data(GeneratePantsReference.BUILD_DICTIONARY_PRODUCT)

  SITE_GEN_PRODUCT = 'generated_site'

  @classmethod
  def product_types(cls):
    return [cls.SITE_GEN_PRODUCT]

  def _process_exported_pages(self):
    markdown_site = self.context.products.get('markdown_html')
    buildroot = get_buildroot()

    markdown_exported_pages = []
    for tgt, prod in markdown_site.itermappings():
      for basedir, product_file_list in prod.items():
        for html_file_product in product_file_list:
          abs_html_path = os.path.join(basedir, html_file_product)
          pg_export = _make_page_export(abs_html_path, tgt.show_toc, buildroot)
          markdown_exported_pages.append(pg_export)

    pants_ref_prod = self.context.products.get_data(
      GeneratePantsReference.PANTS_REFERENCE_PRODUCT)
    markdown_exported_pages.append(
      _make_page_export(pants_ref_prod, False, buildroot))
    build_dict_prod = self.context.products.get_data(
      GeneratePantsReference.BUILD_DICTIONARY_PRODUCT)
    markdown_exported_pages.append(
      _make_page_export(build_dict_prod, False, buildroot))

    return markdown_exported_pages

  def execute(self):
    processed_exported_pages = self._process_exported_pages()

    souped_pages = [soupify(export) for export in processed_exported_pages]

    # Mutates soup objects.
    for pg in souped_pages:
      normalize_hrefs(pg)



def load_config(json_path):
  """Load config info from a .json file and return it."""
  with open(json_path) as json_file:
    config = json.loads(json_file.read().decode('utf8'))
  # sanity-test the config:
  assert(config['tree'][0]['page'] == 'index')
  return config


def load_soups(config):
  """Generate BeautifulSoup AST for each page listed in config."""
  soups = {}
  for page, path in config['sources'].items():
    with open(path, 'rb') as orig_file:
      soups[page] = beautiful_soup(orig_file.read().decode('utf-8'))
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
      if tag.has_attr('pantsmark'):
        pantsmark = tag['pantsmark']
        if pantsmark in accumulator:
          raise TaskError('pantsmarks are unique but "{0}" appears in {1} and {2}'
                          .format(pantsmark, page, accumulator[pantsmark]))

        # To link to a place "mid-page", we need an HTML anchor.
        # If this tag already has such an anchor, use it.
        # Else, make one up.
        anchor = tag.get('id') or tag.get('name')
        if not anchor:
          anchor = pantsmark
          while anchor in existing_anchors:
            count += 1
            anchor = '{0}_{1}'.format(pantsmark, count)
          tag['id'] = anchor
          existing_anchors = find_existing_anchors(soup)

        link = '{0}.html#{1}'.format(page, anchor)
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
      if not 'href' in tag.attrs: continue
      old_rel_path = tag['href'].split('#')[0]
      old_dst = os.path.normpath(os.path.join(old_src_dir, old_rel_path))
      if not old_dst in reverse_directory: continue
      new_dst = reverse_directory[old_dst] + '.html'
      new_rel_path = rel_href(name, new_dst)
      # string replace instead of assign to not loose anchor in foo.html#anchor
      tag['href'] = tag['href'].replace(old_rel_path, new_rel_path, 1)


_heading_re = re.compile('^h[1-6]$')  # match heading tag names h1,h2,h3,...


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
        candidate_id = 'heading_{0}_{1}'.format(snippet, count).lower()
        if not candidate_id in existing_anchors:
          existing_anchors.add(candidate_id)
          tag['id'] = candidate_id
          break


def link_pantsrefs(soups, precomputed):
  """Transorm soups: <a pantsref="foo"> becomes <a href="../foo_page.html#foo">"""
  for (page, soup) in soups.items():
    for a in soup.find_all('a'):
      if a.has_attr('pantsref'):
        pantsref = a['pantsref']
        if not pantsref in precomputed.pantsref:
          raise TaskError('Page {0} has pantsref "{1}" and I cannot find pantsmark for'
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
  if soup.title: return soup.title.string
  if soup.h1: return soup.h1.string
  return ''


def generate_site_toc(config, precomputed, here):
  site_toc = []

  def recurse(tree, depth_so_far):
    for node in tree:
      if 'heading' in node:
        heading = node['heading']
        site_toc.append(dict(depth=depth_so_far,
                             link=None,
                             text=heading,
                             here=False))
      if 'page' in node and node['page'] != 'index':
        dst = node['page']
        if dst == here:
          link = here + '.html'
        else:
          link = os.path.relpath(dst + '.html', os.path.dirname(here))
        site_toc.append(dict(depth=depth_so_far,
                             link=link,
                             text=precomputed.page[dst].title,
                             here=(dst == here)))
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
    raise TaskError('Can\'t compute heading depth of non-heading {0}'.format(tag))
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
  return('{0} {1}'.format(config['sources'][here],
                          datetime.now().isoformat()))


def render_html(dst, config, soups, precomputed, template):
  soup = soups[dst]
  renderer = Renderer()
  title = precomputed.page[dst].title
  topdots = ('../' * dst.count('/'))
  if soup.body:
    body_html = '{0}'.format(soup.body)
  else:
    body_html = '{0}'.format(soup)
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
    with open(dst_path, 'wb') as f:
      f.write(html.encode('utf-8'))


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
  with open(config['template'], 'rb') as template_file:
    template = template_file.read().decode('utf-8')
  return template
