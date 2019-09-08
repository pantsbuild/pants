jar_library(
    name = "libthrift",
    jars = [
        # libthrift is forced due to having a very, very high dependent count
        jar(
            org = "org.apache.thrift",
            name = "libthrift",
            force = True,
            rev = "0.10.0",
            excludes = [
                exclude(
                    org = "org.apache.httpcomponents",
                    name = "httpclient",
                ),  # DPB-9907
                exclude(
                    org = "org.apache.httpcomponents",
                    name = "httpcore",
                ),  # DPB-9907
                exclude(
                    org = "org.slf4j",
                    name = "slf4j-jdk14",
                ),
            ],
        ),
    ],
)

target(
    name = "thrift",
    dependencies = [
        ":libthrift",
        "3rdparty/jvm/commons-lang",
        "3rdparty/jvm/org/slf4j:slf4j-api",
    ],
)

jar_library(
    name = "libfb303-0.7.0",
    jars = [
        jar(
            org = "org.apache.thrift",
            name = "libfb303",
            force = True,
            rev = "0.7.0",
        ),
    ],
    # Loaded reflectively by the hive client.
    scope = "runtime",
)
