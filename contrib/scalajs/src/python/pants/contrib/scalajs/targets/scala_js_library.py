# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.payload import Payload
from pants.build_graph.target import Target

from pants.contrib.scalajs.targets.scala_js_target import ScalaJSTarget


class ScalaJSLibrary(ScalaJSTarget, Target):
  """A library with scala sources, intended to be compiled to Javascript.

  Linking multiple libraries together into a shippable blob additionally requires a
  ScalaJSBinary target.
  """

  def __init__(self, sources=None, address=None, payload=None, **kwargs):
    """
    :param sources: Scala source that makes up this module; paths are relative to the BUILD
                    file's directory.
    :type sources: `globs`, `rglobs` or a list of strings
    """
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources=sources,
                                           sources_rel_path=address.spec_path,
                                           key_arg='sources'),
    })
    super().__init__(address=address, payload=payload, **kwargs)
