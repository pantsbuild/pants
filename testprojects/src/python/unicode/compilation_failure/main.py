# This file is expected to fail to "compile", and raise a unicode error while doing so.
# Because the error itself contains unicode, it can exercise that error handling codepaths
# are unicode aware.
import sys¡
