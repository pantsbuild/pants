# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import base64
import fnmatch
import glob
import hashlib
import json
import os
import zipfile
from builtins import str

from pants.util.contextutil import open_zip, temporary_dir
from pants.util.dirutil import read_file, safe_file_dump


def replace_in_file(workspace, src_file_path, from_str, to_str):
  """Replace from_str with to_str in the name and content of the given file.

  If any edits were necessary, returns the new filename (which may be the same as the old filename).
  """
  from_bytes = from_str.encode('ascii')
  to_bytes = to_str.encode('ascii')
  data = read_file(os.path.join(workspace, src_file_path))
  if from_bytes not in data and from_str not in src_file_path:
    return None

  dst_file_path = src_file_path.replace(from_str, to_str)
  safe_file_dump(os.path.join(workspace, dst_file_path), data.replace(from_bytes, to_bytes))
  if src_file_path != dst_file_path:
    os.unlink(os.path.join(workspace, src_file_path))
  return dst_file_path


def any_match(globs, filename):
  return any(fnmatch.fnmatch(filename, g) for g in globs)


def locate_dist_info_dir(workspace):
  dir_suffix = '*.dist-info'
  matches = glob.glob(os.path.join(workspace, dir_suffix))
  if not matches:
    raise Exception('Unable to locate `{}` directory in input whl.'.format(dir_suffix))
  if len(matches) > 1:
    raise Exception('Too many `{}` directories in input whl: {}'.format(dir_suffix, matches))
  return os.path.relpath(matches[0], workspace)


def fingerprint_file(workspace, filename):
  """Given a relative filename located in a workspace, fingerprint the file.

  Returns a tuple of fingerprint string and size string.
  """
  content = read_file(os.path.join(workspace, filename))
  fingerprint = hashlib.sha256(content)
  return 'sha256={}'.format(base64.b64encode(fingerprint.digest())), str(len(content))


def rewrite_record_file(workspace, src_record_file, mutated_file_tuples):
  """Given a RECORD file and list of mutated file tuples, update the RECORD file in place.

  The RECORD file should always be a member of the mutated files, due to both containing
  versions, and having a version in its filename.
  """
  mutated_files = set()
  dst_record_file = None
  for src, dst in mutated_file_tuples:
    if src == src_record_file:
      dst_record_file = dst
    else:
      mutated_files.add(dst)
  if not dst_record_file:
    raise Exception('Malformed whl or bad globs: `{}` was not rewritten.'.format(src_record_file))

  output_records = []
  for line in read_file(os.path.join(workspace, dst_record_file)).splitlines():
    filename, fingerprint_str, size_str = line.rsplit(',', 3)
    if filename in mutated_files:
      fingerprint_str, size_str = fingerprint_file(workspace, filename)
      output_line = ','.join((filename, fingerprint_str, size_str))
    else:
      output_line = line
    output_records.append(output_line)

  safe_file_dump(os.path.join(workspace, dst_record_file), '\r\n'.join(output_records) + '\r\n')


def reversion(args):
  with temporary_dir() as workspace:
    # Extract the input.
    with open_zip(args.whl_file, 'r') as whl:
      src_filenames = whl.namelist()
      whl.extractall(workspace)

    # Determine the location of the `dist-info` directory.
    dist_info_dir = locate_dist_info_dir(workspace)
    record_file = os.path.join(dist_info_dir, 'RECORD')

    # Load metadata for the input whl.
    with open(os.path.join(workspace, dist_info_dir, 'metadata.json'), 'r') as info:
      metadata = json.load(info)
    input_version = metadata['version']

    # Rewrite and move all files (including the RECORD file), recording which files need to be
    # re-fingerprinted due to content changes.
    dst_filenames = []
    refingerprint = []
    for src_filename in src_filenames:
      if os.path.isdir(os.path.join(workspace, src_filename)):
        continue
      dst_filename = src_filename
      if any_match(args.glob, src_filename):
        rewritten = replace_in_file(workspace, src_filename, input_version, args.target_version)
        if rewritten is not None:
          dst_filename = rewritten
          refingerprint.append((src_filename, dst_filename))
      dst_filenames.append(dst_filename)

    # Refingerprint relevant entries in the RECORD file under their new names.
    rewrite_record_file(workspace, record_file, refingerprint)

    # Create a new output whl in the destination.
    dst_whl_filename = os.path.basename(args.whl_file).replace(input_version, args.target_version)
    dst_whl_file = os.path.join(args.dest_dir, dst_whl_filename)
    with open_zip(dst_whl_file, 'w', zipfile.ZIP_DEFLATED) as whl:
      for dst_filename in dst_filenames:
        whl.write(os.path.join(workspace, dst_filename), dst_filename)

    print('Wrote whl with version {} to {}.\n'.format(args.target_version, dst_whl_file))


def main():
  """Given an input whl file and target version, create a copy of the whl with that version.

  This is accomplished via string replacement in files matching a list of globs. Pass the
  optional `--glob` argument to add additional globs: ie  `--glob='thing-to-match*.txt'`.
  """
  parser = argparse.ArgumentParser()
  parser.add_argument('whl_file',
                      help='The input whl file.')
  parser.add_argument('dest_dir',
                      help='The destination directory for the output whl.')
  parser.add_argument('target_version',
                      help='The target version of the output whl.')
  parser.add_argument('--glob', action='append',
                      default=[
                        '*.dist-info/*',
                        '*-nspkg.pth',
                      ],
                      help='Globs (fnmatch) to rewrite within the whl: may be specified multiple times.')
  args = parser.parse_args()
  reversion(args)

if __name__ == '__main__':
  main()
