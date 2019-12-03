import os
import pathlib
import subprocess
import sys


def main():
  workdir = sys.argv[1]
  config_path = pathlib.Path(workdir) / 'pants.ini'
  config = [f'--pants-config-files={config_path}'] if os.path.isfile(config_path) else []

  cmd = [
    './pants',
    '--no-pantsrc',
    '--print-exception-stacktrace=True',
    f'--pants-workdir={workdir}',
  ] + config + ['goals']
  print(f'Running pants with command {cmd}')
  subprocess.run(cmd, check=True)


if __name__ == '__main__':
  main()
