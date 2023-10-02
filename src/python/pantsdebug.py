import pydevd_pycharm
import os


_should_stop = False

def settrace_5678(stop=None):
    should_stop = stop if stop is not None else _should_stop
    if should_stop and os.getenv('PYDEVD_DEBUG_PANTS') == '1':
        pydevd_pycharm.settrace('localhost', port=5678, stdoutToServer=True, stderrToServer=True)
    return
