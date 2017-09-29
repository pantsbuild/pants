#!/bin/bash -eu

# Fetches protoc 3.4.1 if it's missing in the same style as BinaryUtil.
# Compile protos with that protoc, outputting into source repository.

here="$(cd $(dirname "${BASH_SOURCE[0]}") && pwd)"

case "$(uname)" in
  "Darwin")
    os="mac"
    base="$(uname -r)"
    os_version="10.$(( ${base%%.*} - 4))"
    ;;
  "Linux")
    os="linux"
    os_version="$(arch)"
    ;;
  *)
    echo >&2 "Unknown platform when fetching protoc"
    exit 1
    ;;
esac

path="bin/protobuf/${os}/${os_version}/3.4.1/protoc"
cache_path="${HOME}/.cache/${path}"

if [ ! -x "${cache_path}" ]; then
  mkdir -p "$(dirname "${cache_path}")"
  curl "https://binaries.pantsbuild.org/${path}" > "${cache_path}"
  chmod 0755 "${cache_path}"
fi

thirdpartyprotobuf="../../../../../3rdparty/protobuf"
googleapis="${thirdpartyprotobuf}/googleapis"
outdir="${here}/src"
mkdir -p "${outdir}"

"${cache_path}" --rust_out="${outdir}" --grpc_out="${outdir}" --plugin=protoc-gen-grpc="${HOME}/.cache/pants/rust-toolchain/bin/grpc_rust_plugin" --proto_path="${googleapis}" --proto_path="${thirdpartyprotobuf}/standard" "${googleapis}"/{google/rpc/status.proto,google/devtools/remoteexecution/v1test/remote_execution.proto}
