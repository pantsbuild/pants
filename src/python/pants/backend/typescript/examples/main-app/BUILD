package_json(
    scripts=[
        node_build_script(entry_point="build", output_directories=["dist"]),
        node_test_script(entry_point="test")
    ],
    dependencies=[":tsconfig"]
)

file(name="tsconfig", source="tsconfig.json")