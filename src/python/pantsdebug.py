import pydevd_pycharm


def settrace_5678():
    pydevd_pycharm.settrace('localhost', port=5678, stdoutToServer=True, stderrToServer=True)
    return
