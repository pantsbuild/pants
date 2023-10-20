import pydevd_pycharm

import os

def settrace_5678():
    pydevd_pycharm.settrace('localhost', port=5678, stdoutToServer=True, stderrToServer=True)
    return
