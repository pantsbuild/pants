#!/bin/bash -eu

# Compile protos with protoc, outputting into source repository.

here="$(cd $(dirname "${BASH_SOURCE[0]}") && pwd)"
REPO_ROOT="$(dirname "$(dirname "$(dirname "$(dirname "$(dirname "${here}")")")")")"

protoc="$("${REPO_ROOT}/build-support/bin/download_binary.sh" "binaries.pantsbuild.org" "protobuf" "3.4.1" "protoc")"

thirdpartyprotobuf="../../../../../3rdparty/protobuf"
googleapis="${thirdpartyprotobuf}/googleapis"
outdir="${here}/src"
mkdir -p "${outdir}"

"${protoc}" --rust_out="${outdir}" --grpc_out="${outdir}" --plugin=protoc-gen-grpc="${HOME}/.cache/pants/rust/cargo/bin/grpc_rust_plugin" --proto_path="${googleapis}" --proto_path="${thirdpartyprotobuf}/standard" "${googleapis}"/{google/devtools/remoteexecution/v1test/remote_execution.proto,google/bytestream/bytestream.proto,google/rpc/{code,status}.proto,google/longrunning/operations.proto} "${thirdpartyprotobuf}/standard/google/protobuf/empty.proto"
