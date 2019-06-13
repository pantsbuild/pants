import os
import subprocess
import sys


def main():
  workdir = sys.argv[1]
  config = os.path.join(workdir, 'pants.ini')

  cmd = './pants --no-pantsrc --pants-config-files={config} --print-exception-stacktrace=True --pants-workdir={workdir} goals'.format(
    config=config,
    workdir=workdir,
  )
  print(cmd)
  subprocess.run(cmd, shell=True, check=True)

if __name__ == '__main__':
  main()
