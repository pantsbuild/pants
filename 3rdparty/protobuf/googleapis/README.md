This is a dump of the .proto files from https://github.com/googleapis/googleapis directory google.

This dump was taken at git sha e17dbfb19652240490cae8adeb89991d13cf9df7.

It is a selective view of only the protos we actually need.

The following script was run to enable Bytes fields for Rust:
```
sed -i '' '/^package /a\
\
import "rustproto.proto";\
option (rustproto.carllerche_bytes_for_bytes_all) = true;\
' {google/devtools/remoteexecution/v1test/remote_execution.proto,google/bytestream/bytestream.proto,google/rpc/{code,status}.proto,google/longrunning/operations.proto}
```
