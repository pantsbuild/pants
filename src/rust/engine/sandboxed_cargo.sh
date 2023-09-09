# THis simply exists because `shell_command` at the time of writing doesn't know how to merge `PATH`
# from the rule's env and the `extra_env_vars`.

PYTHON_PATH=${CHROOT}/3rdparty/tools/python3/python/bin
RUST_TOOLCHAIN_PATH=${CHROOT}/3rdparty/tools/rust/rust-toolchain/bin
PROTOC_PATH=${CHROOT}/3rdparty/tools/protoc/protoc/bin

PATH=$PATH:$PYTHON_PATH:$RUST_TOOLCHAIN_PATH:$PROTOC_PATH
cargo "$@"
