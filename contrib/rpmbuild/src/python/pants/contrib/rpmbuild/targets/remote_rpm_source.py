# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.resources import Resources


class RemoteRpmSource(Resources):
  """Represent a versioned bundle or file that can be used as source input during RPM builds."""

  @classmethod
  def alias(cls):
    return 'remote_rpm_source'

  def __init__(
    self,
    name=None,
    filename=None,
    version=None,
    platform=None,
    arch=None,
    namespace=None,
    extract=None,
    payload=None,
    **kwargs):
    """
    Represent a remote source to be fetched as part of the RpmBuild process.

    :param string name: Basename of the source package or file, as well as the target name.
      e.g. 'node.tar.gz' or 'thrift'.
    :param string version: version of the source distribution.
    :param string platform: Intended platform. Currently defaults to linux
    :param string arch: Intended architecture of the package. Currently defaults to 'x86_64'.
    :param string filename: Name of the file intended for fetching. Defaults to the target name.
    :param string namespace: Directory name that holds these sources. Defaults to using the split filename,
      e.g. 'node' for 'node.tar.gz' or 'thrift' for 'thrift'. This argument is mostly for tricky edge cases.
    :param bool extract: When True, remote source will be extracted. Supports
      archive types understood by `pants.fs.archive.archiver_for_path(filename)`.
    """

    # TODO(mateo): Support platform-independent bundles, which is what most source distributions will be.
    # TODO(mateo): Add a 'release' param. For now, I have been rolling it into the version field or hardcoding it.
    self.version = version
    self.platform = platform or 'linux'
    self.arch = arch or 'x86_64'
    self.filename = filename or name
    self.namespace = namespace or self.filename.split('.')[0]
    self.extract = extract
    payload = payload or Payload()
    payload.add_fields({
      'version': PrimitiveField(self.version),
      'platform': PrimitiveField(self.platform),
      'arch': PrimitiveField(self.arch),
      'filename': PrimitiveField(self.filename),
      'namespace': PrimitiveField(self.namespace),
      'extract': PrimitiveField(self.extract),
    })
    super(RemoteRpmSource, self).__init__(name=name, payload=payload, **kwargs)
