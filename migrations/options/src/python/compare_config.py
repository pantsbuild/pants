# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import OrderedDict
import itertools
import sys

from pants.option.config import Config


def compare_config(config_paths):
  """Prints out keys that are provided in at least two of the specified config_paths.

  Emits a faux pants.ini-like output:

  [section]
  key: val1  # file1
       val2  # file2
       val3  # file3
  ...
  """

  def load_config(p):
    """We need direct access to the underlying configparser, so we don't load via Config."""
    cp = Config._create_parser()
    with open(p, 'r') as ini:
      cp.readfp(ini)
    return cp

  configs = [load_config(path) for path in config_paths]

  def get_keys(c, s):
    """Return all keys provided in section s of config c."""
    if s == 'DEFAULT':
      return [k for k in c._defaults.keys()]
    elif c.has_section(s):
      return [k for k in c._sections[section].keys() if k != '__name__']
    else:
      return []

  def get_vals(s, k):
    """Returns a the values of key k in section s in each of the configs.

    Return value is a list of (path, value). The value will be None if the config at path had no
    value for the key.
    """
    def safe_get(c):
      if c.has_option(s, k):
        return c.get(s, k)
      else:
        return None
    return list((p, safe_get(config)) for p, config in zip(config_paths, configs))

  def uniq(it):
    """Returns the unique items in it, sorting the items as a byproduct."""
    return [x for x, _ in itertools.groupby(sorted(it))]

  # De-duped list of all known sections.
  all_sections = (['DEFAULT'] +
                  uniq(itertools.chain.from_iterable(config.sections() for config in configs)))

  # Map of section -> (map of key->list of (path, value) for that key).
  compared_config = OrderedDict()

  for section in all_sections:
    all_keys = uniq(itertools.chain.from_iterable(get_keys(config, section) for config in configs))
    section_dict = OrderedDict((key, get_vals(section, key)) for key in all_keys)
    compared_config[section] = section_dict

  def pretty(x):
    """Indent the continuation lines of x, if any."""
    if x is None:
      return 'None'
    lines = x.decode('utf8').split('\n')
    if len(lines) > 1:
      return '\n'.join([lines[0]] +
                       ['    {}'.format(l) for l in lines[1:-1]] +
                       ['  {}'.format(lines[-1])])
    else:
      return x

  def val_line(prefix, path_and_val):
    """The value line, annotated with the path of the config which was the source of this value."""
    return '{}{}  # {}'.format(prefix, pretty(path_and_val[1]), path_and_val[0]).encode('utf8')

  for section, section_dict in compared_config.items():
    section_header = '\n[{}]'.format(section)
    for key, vals in section_dict.items():
      if len([v for v in vals if v[1] is not None]) > 1:
        if section_header:
          # Only print section_header if we actually have anything to say about that section.
          print(section_header)
          section_header = None
        key_str = '{}: '.format(key)
        indent = ' ' * len(key_str)
        print(val_line(key_str, vals[0]))
        for v in vals[1:]:
          print(val_line(indent, v))
        print(b'')


if __name__ == '__main__':
  compare_config(sys.argv[1:])
