NB: The native engine is integrated into the pants codebase via `native.py` in
this directory along with `build-support/bootstrap_native` which ensures a
pants native engine library is built and available for linking. The glue is the
sha1 hash of the native engine source code used as its version by the `Native`
subsystem. This hash is maintained by `build-support/bootstrap_native` and
output to the `native_engine_version` file in this directory. Any modification
to this resource files location will need adjustments in
`build-support/bootstrap_native` to ensure the linking continues to work.
