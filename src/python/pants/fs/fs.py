# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import os

# The max filename length for HFS+, extX and NTFS is 255, but many systems also have limits on the
# total path length (made up of multiple filenames), so we include some additional buffer.
_MAX_FILENAME_LENGTH = 100


def safe_filename(name, extension=None, digest=None, max_length=_MAX_FILENAME_LENGTH):
    """Creates filename from name and extension ensuring that the final length is within the
    max_length constraint.

    By default the length is capped to work on most filesystems and the fallback to achieve
    shortening is a sha1 hash of the proposed name.

    Raises ValueError if the proposed name is not a simple filename but a file path.
    Also raises ValueError when the name is simple but cannot be satisfactorily shortened with the
    given digest.

    :API: public

    name:       the proposed filename without extension
    extension:  an optional extension to append to the filename
    digest:     the digest to fall back on for too-long name, extension concatenations - should
                support the hashlib digest api of update(string) and hexdigest
    max_length: the maximum desired file name length
    """
    if os.path.basename(name) != name:
        raise ValueError("Name must be a filename, handed a path: {}".format(name))

    ext = extension or ""
    filename = name + ext
    if len(filename) <= max_length:
        return filename
    else:
        digest = digest or hashlib.sha1()
        digest.update(filename.encode())
        hexdigest = digest.hexdigest()[:16]

        # Prefix and suffix length: max length less 2 periods, the extension length, and the digest length.
        ps_len = max(0, (max_length - (2 + len(ext) + len(hexdigest))) // 2)
        sep = "." if ps_len > 0 else ""
        prefix = name[:ps_len]
        suffix = name[-ps_len:] if ps_len > 0 else ""

        safe_name = "{}{}{}{}{}{}".format(prefix, sep, hexdigest, sep, suffix, ext)
        if len(safe_name) > max_length:
            raise ValueError(
                "Digest {} failed to produce a filename <= {} "
                "characters for {} - got {}".format(digest, max_length, filename, safe_name)
            )
        return safe_name


def safe_filename_from_path(path, **kwargs):
    """As for `safe_filename`, but takes a path.

    First converts it into a name by replacing separator characters, and then calls safe_filename.
    """
    return safe_filename(path.strip(os.path.sep).replace(os.path.sep, "."), **kwargs)
