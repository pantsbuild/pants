jvm_binary(
    main = "org.pantsbuild.testproject.jsresources.JsResourcesMain",
    source = "JsResourcesMain.java",
    dependencies = [
        "3rdparty:guava",
        "contrib/node/examples/src/node/web-component-button:web-component-button-processed",
    ],
)

jvm_binary(
    name = "jsresources-with-dependency-artifacts",
    main = "org.pantsbuild.testproject.jsresources.JsResourcesMain",
    source = "JsResourcesMain.java",
    dependencies = [
        "3rdparty:guava",
        "contrib/node/examples/src/node/web-component-button:web-component-button-processed-with-dependency-artifacts",
    ],
)
