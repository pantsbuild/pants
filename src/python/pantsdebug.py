import pydevd_pycharm
import os

def settrace_5678():
    if os.getenv('PYDEVD_DEBUG_PANTS') == '1':
        pydevd_pycharm.settrace('localhost', port=5678, stdoutToServer=True, stderrToServer=True)
    return
