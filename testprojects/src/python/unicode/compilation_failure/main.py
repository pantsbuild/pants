# This file is expected to fail to "compile" when run via `./pants run` due to a SyntaxError.
# Because the error itself contains unicode, it can exercise that error handling codepaths
# are unicode aware.

if __name__ == '__main__':
    import sys¡
