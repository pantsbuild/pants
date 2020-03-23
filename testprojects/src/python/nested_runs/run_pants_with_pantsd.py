import pathlib
import subprocess
import sys


def main():
    workdir = sys.argv[1]
    config_path = pathlib.Path(workdir) / "pants.toml"
    config = [f"--pants-config-files={config_path}"] if config_path.is_file() else []

    cmd = (
        [
            "./pants.pex",
            "--no-pantsrc",
            "--print-exception-stacktrace=True",
            f"--pants-workdir={workdir}",
        ]
        + config
        + ["goals"]
    )
    print(f"Running pants with command {cmd}")
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
