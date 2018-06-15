python_library(
    provides = setup_py(
        name = "test_pants_plugin",
        description = "A test pants plugin",
        namespace_packages = [
            "test_pants_plugin",
            "test_pants_plugin.subsystems",
        ],
        version = "0.0.1",
    ),
    dependencies = [
        "testprojects/pants-plugins/3rdparty/python/pants",
        "testprojects/pants-plugins/src/python/test_pants_plugin/subsystems",
    ],
)
