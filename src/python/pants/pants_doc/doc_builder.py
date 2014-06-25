# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import pkgutil
import shutil


try:
  import markdown
  HAS_MARKDOWN = True
except ImportError:
  HAS_MARKDOWN = False


from pants import is_doc  # XXX This no longer exists
from pants.base.generator import Generator

_TEMPLATE_BASEDIR = 'templates'

class DocBuilder(object):
  def __init__(self, root_dir):
    self.root_dir = root_dir

  def build(self, targets, _):
    template_path = os.path.join(_TEMPLATE_BASEDIR, 'doc.mustache')
    template = pkgutil.get_data(__name__, template_path)
    for target in targets:
      assert is_doc(target), 'DocBuilder can only build DocTargets, given %s' % str(target)
      base_dir = os.path.dirname(target.address.build_file.full_path)
      target_base = target.target_base
      print('building doc for %s' % str(target))
      output_dir = os.path.normpath(os.path.join(self.root_dir, target.id))
      if not os.path.exists(output_dir):
        os.makedirs(output_dir)
      for filename in target.sources:
        if filename.endswith('md'):
          if not HAS_MARKDOWN:
            print('Missing markdown, cannot process %s' % filename, file=sys.stderr)
          else:
            print('processing %s' % filename)
            html_filename = os.path.splitext(filename)[0] + '.html'
            output_filename = os.path.join(output_dir, os.path.basename(html_filename))
            print('writing file to %s' % output_filename)
            with open(output_filename, 'w') as output:
              with open(os.path.join(target_base, filename), 'r') as md:
                contents = md.read()
                md_html = markdown.markdown(contents)
                generator = Generator(template, root_dir = self.root_dir, text = md_html)
              generator.write(output)
      for filename in target.resources:
        full_filepath = os.path.join(target_base, filename)
        target_file = os.path.join(output_dir, os.path.relpath(full_filepath, base_dir))
        print('copying %s to %s' % (filename, target_file))
        if not os.path.exists(os.path.dirname(target_file)):
          os.makedirs(os.path.dirname(target_file))
        shutil.copy(full_filepath, target_file)
    return 0
