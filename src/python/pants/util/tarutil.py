# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import tarfile


class TarFile(tarfile.TarFile):
  def next(self):
    """A modification of the original next() method in tarfile module

    Raise InvalidHeaderError whenever seen as long as ignore_zeros is not set
    """
    self._check("ra")
    if self.firstmember is not None:
      m = self.firstmember
      self.firstmember = None
      return m

    # Advance the file pointer.
    if self.offset != self.fileobj.tell():
      self.fileobj.seek(self.offset - 1)
      if not self.fileobj.read(1):
        raise tarfile.ReadError("unexpected end of data")

    # Read the next block.
    tarinfo = None
    while True:
      try:
        tarinfo = self.tarinfo.fromtarfile(self)
      except tarfile.EOFHeaderError as e:
        if self.ignore_zeros:
          self._dbg(2, "0x%X: %s" % (self.offset, e))
          self.offset += tarfile.BLOCKSIZE
          continue
      except tarfile.InvalidHeaderError as e:
        if self.ignore_zeros:
          self._dbg(2, "0x%X: %s" % (self.offset, e))
          self.offset += tarfile.BLOCKSIZE
          continue
        elif self.errorlevel > 0:
          raise tarfile.ReadError(str(e))
      except tarfile.EmptyHeaderError:
        if self.offset == 0:
          raise tarfile.ReadError("empty file")
      except tarfile.TruncatedHeaderError as e:
        if self.offset == 0:
          raise tarfile.ReadError(str(e))
      except tarfile.SubsequentHeaderError as e:
        raise tarfile.ReadError(str(e))
      break

    if tarinfo is not None:
      self.members.append(tarinfo)
    else:
      self._loaded = True

    return tarinfo
