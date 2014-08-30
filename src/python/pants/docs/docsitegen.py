# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

"""Static Site Generator for the Pants Build documentation site.

Suggested use:
  cd pants
  ./build-support/bin/publish_docs.sh # invokes docsitegen.py
"""

import os
import sys
import bs4
import pystache
import shutil
import yaml

def load_config(yaml_path):
  config = yaml.load(file(yaml_path).read().decode('utf8'))
  # do some sanity-testing on the config:
  assert(config['tree'][0]['page'] == 'index')
  return config

def load_soups(config):
  """Generate BeautifulSoup AST for each page"""
  soups = {}
  for page, path in config['sources'].items():
    soups[page] = bs4.BeautifulSoup(open(path).read().decode('utf8'))
  return soups

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
      new_rel_path = os.path.relpath(new_dst + ".html", new_src_dir)
      # string replace instead of assign to not loose anchor in foo.html#anchor
      tag['href'] = tag['href'].replace(old_rel_path, new_rel_path, 1)

def transform_soups(config, soups):
  """Mutate our soups to be better when we write them out later."""
  fixup_internal_links(config, soups)

def get_title(soup):
  if soup.title: return soup.title.string
  if soup.h1: return soup.h1.string
  return ''

def render_html(config, dst, soup):
  template = open(config['template']).read().encode('utf8')
  renderer = pystache.Renderer()
  title = get_title(soup) or dst
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

def write_en_pages(config, soups):
  outdir = config['outdir']
  for dst, soup in soups.items():
    dst_path = os.path.join(outdir, dst + ".html")
    dst_dir = os.path.dirname(dst_path)
    if not os.path.isdir(dst_dir):
      os.makedirs(dst_dir)
    html = render_html(config, dst, soup)
    f = open(dst_path, 'w')
    f.write(html.encode('utf8'))
    f.close()

def copy_extras(config):
  """copy over "extra" files named in config yaml: stylesheets, logos, ..."""
  outdir = config['outdir']
  for dst, src in config['extras'].items():
    dst_path = os.path.join(outdir, dst)
    dst_dir = os.path.dirname(dst_path)
    if not os.path.isdir(dst_dir):
      os.makedirs(dst_dir)
    shutil.copy(src, dst_path)

def main():
  config = load_config(sys.argv[1])
  soups = load_soups(config)
  transform_soups(config, soups)
  write_en_pages(config, soups)
  copy_extras(config)

if __name__ == "__main__":
  sys.exit(main())
