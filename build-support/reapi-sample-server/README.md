The `run.sh` script in this directory launches a very basic / insecure instance of the https://buildgrid.build/ remote execution service inside a single Docker container.

To use it to experiment with Pants' remote execution implementation, you'd start the server in one shell with `run.sh`, and then use Pants config similar to the following to enable it:
```toml pants.toml
remote_execution = true
remote_store_address = "grpc://127.0.0.1:50051"
remote_execution_address = "grpc://127.0.0.1:50051"
remote_instance_name = ""
# TODO: See https://gitlab.com/BuildGrid/buildgrid/-/blob/master/buildgrid/server/server.py#L212-222
process_execution_remote_parallelism = 8
```
