# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

"""Static Site Generator for the Pants Build documentation site.

Suggested use:
  cd pants
  ./build-support/bin/publish_docs.sh  # invokes sitegen.py
"""

import collections
import json
import os
import re
import shutil

import bs4
import pystache

from pants.backend.core.tasks.task import Task
from pants.base.exceptions import TaskError


class SiteGen(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(SiteGen, cls).setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag('config-path'),
                            dest='sitegen_config_path',
                            action='append',
                            help='[%default] Path to .json file describing site structure.')

  def execute(self):
    if not self.context.options.sitegen_config_path:
      raise TaskError('Need to pass '
                      '--sitegen-config-path=src/python/pants/docs/docsite.json'
                      ' or something.')
    for config_path in self.context.options.sitegen_config_path:
      config = load_config(config_path)
      soups = load_soups(config)
      precomputed = precompute(config, soups)
      transform_soups(config, soups, precomputed)
      template = load_template(config)
      write_en_pages(config, soups, precomputed, template)
      copy_extras(config)


def load_config(json_path):
  """Load config info from a .json file and return it"""
  with open(json_path) as json_file:
    config = json.loads(json_file.read().decode('utf8'))
  # sanity-test the config:
  assert(config['tree'][0]['page'] == 'index')
  return config


def load_soups(config):
  """Generate BeautifulSoup AST for each page listed in config"""
  soups = {}
  for page, path in config['sources'].items():
    with open(path, 'rb') as orig_file:
      soups[page] = bs4.BeautifulSoup(orig_file.read().decode('utf-8'))
  return soups


class Precomputed(object):
  """Info we compute (and preserve) before we mutate things."""

  def __init__(self, page):
    """
    :param page: dictionary of per-page precomputed info
    """
    self.page = page


class PrecomputedPageInfo(object):
  """Info we compute (and preserve) for each page before we mutate things."""

  def __init__(self, title):
    """
    :param title: Page title
    """
    self.title = title


def precompute(config, soups):
  """Return info we want to compute (and preserve) before we mutate things."""
  page = {}
  for p, soup in soups.items():
    title = get_title(soup) or p
    page[p] = PrecomputedPageInfo(title=title)
  return Precomputed(page=page)


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
    new_src_dir = os.path.dirname(name)
    for tag in soup.find_all(True):
      if not 'href' in tag.attrs: continue
      old_rel_path = tag['href'].split('#')[0]
      old_dst = os.path.normpath(os.path.join(old_src_dir, old_rel_path))
      if not old_dst in reverse_directory: continue
      new_dst = reverse_directory[old_dst]
      new_rel_path = os.path.relpath(new_dst + '.html', new_src_dir)
      # string replace instead of assign to not loose anchor in foo.html#anchor
      tag['href'] = tag['href'].replace(old_rel_path, new_rel_path, 1)


_heading_re = re.compile('^h[1-6]$')  # match heading tag names h1,h2,h3,...


def ensure_headings_linkable(soups):
  """foreach soup, foreach h1,h2,etc, if no id=... or name=..., give it one.

  Enables tables of contents.
  """
  for soup in soups.values():
    # To avoid re-assigning an existing id, note 'em down.
    # Case-insensitve because distinguishing links #Foo and #foo would be weird.
    existing_ids = set([])
    for tag in soup.find_all(True):
      existing_ids.add((tag.get('id') or '').lower())
      existing_ids.add((tag.get('name') or '').lower())
    count = 100
    for tag in soup.find_all(_heading_re):
      if not (tag.has_attr('id') or tag.has_attr('name')):
        snippet = ''.join([c for c in tag.text if c.isalpha()])[:20]
        while True:
          count += 1
          candidate_id = 'heading_{0}_{1}'.format(snippet, count).lower()
          if not candidate_id in existing_ids:
            existing_ids.add(candidate_id)
            tag['id'] = candidate_id
            break


def transform_soups(config, soups, precomputed):
  """Mutate our soups to be better when we write them out later."""
  fixup_internal_links(config, soups)
  ensure_headings_linkable(soups)
  # TODO: yet more to come here


def get_title(soup):
  """Given a soup, pick out a title"""
  if soup.title: return soup.title.string
  if soup.h1: return soup.h1.string
  return ''


def generate_site_toc(config, precomputed, here):
  site_toc = []
  def recurse(tree, depth_so_far):
    for node in tree:
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


def generate_breadcrumbs(config, precomputed, here):
  """return template data for breadcrumbs"""
  breadcrumb_pages = []
  def recurse(tree, pages_so_far):
    for node in tree:
      if 'page' in node:
        pages_so_far = pages_so_far + [node['page']]
      if 'page' in node and node['page'] == here:
        return pages_so_far
      if 'children' in node:
        r = recurse(node['children'], pages_so_far)
        if r:
          return r
    return None

  if 'tree' in config:
    r = recurse(config['tree'], [])
    if r:
      breadcrumb_pages = r
  breadcrumbs_template_data = []
  for page in breadcrumb_pages:
    breadcrumbs_template_data.append(dict(
        link=os.path.relpath(page + '.html', os.path.dirname(here)),
        text=precomputed.page[page].title))
  return breadcrumbs_template_data


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


def generate_page_toc(soup):
  """Return page-level (~list of headings) TOC template data for soup"""
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


def render_html(dst, config, soups, precomputed, template):
  soup = soups[dst]
  renderer = pystache.Renderer()
  title = precomputed.page[dst].title
  topdots = ('../' * dst.count('/'))
  if soup.body:
    body_html = '{0}'.format(soup.body)
  else:
    body_html = '{0}'.format(soup)
  page_toc = generate_page_toc(soup)
  html = renderer.render(template,
                         body_html=body_html,
                         breadcrumbs=generate_breadcrumbs(config, precomputed, dst),
                         site_toc=generate_site_toc(config, precomputed, dst),
                         has_page_toc=bool(page_toc),
                         page_toc=page_toc,
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
