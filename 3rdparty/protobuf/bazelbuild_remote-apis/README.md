This is a dump of the .proto files from https://github.com/bazelbuild/remote-apis directory build.

This dump was taken at git sha cbf6ada7f5b2a0ce14646bf983d03b49118f0ec8.

The following script was run to enable Bytes fields for Rust:
```
sed -i '' '/^package /a\
\
import "rustproto.proto";\
option (rustproto.carllerche_bytes_for_bytes_all) = true;\
' build/bazel/remote/execution/v2/remote_execution.proto
```
