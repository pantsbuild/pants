# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

'''Static Site Generator for the Pants Build documentation site.

Suggested use:
  cd pants
  ./build-support/bin/publish_docs.sh  # invokes sitegen.py
'''

import json
import os
import shutil
import pystache

import bs4

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
  '''Load config info from a .json file and return it'''
  with open(json_path) as json_file:
    config = json.loads(json_file.read().decode('utf8'))
  # sanity-test the config:
  assert(config['tree'][0]['page'] == 'index')
  return config


def load_soups(config):
  '''Generate BeautifulSoup AST for each page listed in config'''
  soups = {}
  for page, path in config['sources'].items():
    with open(path, 'rb') as orig_file:
      soups[page] = bs4.BeautifulSoup(orig_file.read().decode('utf-8'))
  return soups


class Precomputed(object):
  '''Info we compute (and preserve) before we mutate things.'''

  def __init__(self, page):
    '''
    :param page: dictionary of per-page precomputed info
    '''
    self.page = page


class PrecomputedPageInfo(object):
  '''Info we compute (and preserve) for each page before we mutate things.'''

  def __init__(self, title):
    '''
    :param title: Page title
    '''
    self.title = title


def precompute(config, soups):
  '''Return info we want to compute (and preserve) before we mutate things.'''
  page = {}
  for p, soup in soups.items():
    title = get_title(soup) or p
    page[p] = PrecomputedPageInfo(title=title)
  return Precomputed(page=page)


def fixup_internal_links(config, soups):
  '''Find href="..." links that link to pages in our docset; fix them up.

  We don't preserve relative paths between files as we copy-transform them
  from source to dest. So adjust the paths to work with new locations.
  '''
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


def transform_soups(config, soups, precomputed):
  '''Mutate our soups to be better when we write them out later.'''
  fixup_internal_links(config, soups)
  # TODO: more to come here


def get_title(soup):
  '''Given a soup, pick out a title'''
  if soup.title: return soup.title.string
  if soup.h1: return soup.h1.string
  return ''


def render_html(dst, config, soups, precomputed, template):
  soup = soups[dst]
  renderer = pystache.Renderer()
  title = precomputed.page[dst].title
  topdots = ('../' * dst.count('/'))
  if soup.body:
    body_html = soup.body.prettify()
  else:
    body_html = soup.prettify()
  html = renderer.render(template,
                         body_html=body_html,
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
  '''copy over "extra" files named in config json: stylesheets, logos, ...'''
  outdir = config['outdir']
  for dst, src in config['extras'].items():
    dst_path = os.path.join(outdir, dst)
    dst_dir = os.path.dirname(dst_path)
    if not os.path.isdir(dst_dir):
      os.makedirs(dst_dir)
    shutil.copy(src, dst_path)


def load_template(config):
  '''Return text of template file specified in config'''
  with open(config['template'], 'rb') as template_file:
    template = template_file.read().decode('utf-8')
  return template
