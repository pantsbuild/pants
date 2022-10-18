The `run.sh` script in this directory launches a very basic / insecure instance of the https://buildgrid.build/ remote execution service inside a single Docker container.

To use it to experiment with Pants' remote execution implementation, you'd start the server in one shell with `run.sh`. Then, set a target like `python_test` to use `environment='remote'`, and run Pants with `--pants-config-files=pants.remote-execution.toml`.
