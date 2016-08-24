# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import tarfile

import six


if six.PY2:
  class TarFile(tarfile.TarFile):
    def next(self):
      """A copy and modification of the next() method in tarfile module.

      The copy is from tarfile.py of CPython @102457:95df96aa2f5a

      # Copyright (C) 2002 Lars Gustäbel <lars@gustaebel.de>
      # All rights reserved.
      #
      # Permission  is  hereby granted,  free  of charge,  to  any person
      # obtaining a  copy of  this software  and associated documentation
      # files  (the  "Software"),  to   deal  in  the  Software   without
      # restriction,  including  without limitation  the  rights to  use,
      # copy, modify, merge, publish, distribute, sublicense, and/or sell
      # copies  of  the  Software,  and to  permit  persons  to  whom the
      # Software  is  furnished  to  do  so,  subject  to  the  following
      # conditions:
      #
      # The above copyright  notice and this  permission notice shall  be
      # included in all copies or substantial portions of the Software.
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
          # Modify here, to raise exceptions if errorlevel is bigger than 0.
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
else:
  TarFile = tarfile.TarFile
