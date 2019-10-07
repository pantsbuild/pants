import pathlib
import subprocess
import sys


def main():
    workdir = sys.argv[1]
    config = pathlib.Path(workdir) / "pants.ini"

    cmd = [
        "./pants",
        "--no-pantsrc",
        f"--pants-config-files={config}",
        "--print-exception-stacktrace=True",
        f"--pants-workdir={workdir}",
        "goals",
    ]
    print(f"Running pants with command {cmd}")
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
