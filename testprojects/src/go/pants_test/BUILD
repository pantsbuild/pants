go_package(
    # import_path="github.com/toolchainlabs/toolchain/src/go/src/toolchain/pants_test",
    import_path="main",
    dependencies=["./bar:bar"],
)

go_binary(
    name="bin",
    binary_name="bin",
    main=":pants_test",
)
