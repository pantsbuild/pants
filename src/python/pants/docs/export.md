Export Format
=============


The configuration for a set of targets can be exported out of pants into JSON format using
the `pants export` goal.  This could useful for integrating Pants with another build tool.
The [Pants Support IntelliJ plugin](https://github.com/pantsbuild/intellij-pants-plugin) uses
the export goal to get information out of Pants to configure IntelliJ.

This page captures the specification of the data provided by the export goal.
See the Changelog section below for differences between versions of the export format.

# Top Level fields

  - "version" :  A string representing the version number of the export format.
  - "libraries" : Dictionary of paths to .jar files resolved by pants required to compile the
  project.
  - "targets" : Dictionary of targets defined in BUILD files.
  - "distributions" : Information about JVM distributions.
  - "jvm_platforms" : Information about JVM platforms(language level and additionals arguments).
  - "python_setup" : Information about Python setup(interpreters and chroots for them).

## Version

Version number for identifying the export file format output. This version number will
change when there is a change to the output format.  The version number specification is as follows:

`<major_version>.<minor_version>.<patch_version>`

  - `<major_version>` : Increment this field when there is a major format change
  - `<minor_version>` : Increment this field when there is a minor change that breaks backward
     compatibility for an existing field or a field is removed.
  - `<patch_version>` : Increment this field when a minor format change that just adds information
     that an application can safely ignore.


## Libraries

Represents all of the external jars that have been resolved by pants.  The value for libraries
is represented by a dictionary as follows:

`{ <jar_coordinate> : { <conf_name> : <jar_file> } }`

  - `<jar_coordinate>` : key representing this jar.  Usually `<org>:<name>:<rev>`
  - `<conf_name>` : Ivy conf this jar was resolved for.  Usually one of `default`, `sources`,
    or `javadoc`
  - `<jar_file>` : Path to the resolved jar file.

## Targets

The targets field contains all of the targets exported from pants BUILD file definitions.  The
value for targets is represented by a dctionary of target specs mapped to a dictionary of the
fields defined in the target:

`{ <target_spec> : <target_field_mapping> }`

  - `<target_spec>` :  `"<path_to_build_file>:<target_name>"`
  - `<target_field_mapping>` : Dictionary of target fields  (TBD)


# Example export output

The following is an abbreviated export file from a command in the pants repo:

```
{
    "version": "1.0.4",
    "libraries": {
        "commons-logging:commons-logging:1.1.1": {
            "default": "/Users/user/.ivy2/pants/commons-logging/commons-logging/jars/commons-logging-1.1.1.jar"
        },
        "commons-codec:commons-codec:1.6": {
            "default": "/Users/user/.ivy2/pants/commons-codec/commons-codec/jars/commons-codec-1.6.jar"
        },
        "org.apache.httpcomponents:httpclient:4.2.5": {
            "default": "/Users/user/.ivy2/pants/org.apache.httpcomponents/httpclient/jars/httpclient-4.2.5.jar"
        },
        ...
    },
    # distributions settings provided as an example from another repo
    "distributions": {
        "darwin": [
            "/Library/Java/JavaVirtualMachines/jdk1.8.0_45.jdk/Contents/Home",
            "/Library/Java/JavaVirtualMachines/jdk1.7.0_80.jdk/Contents/Home"
        ],
        "linux": [
            "/usr/java/jdk1.8.0_45",
            "/usr/java/jdk1.7.0_80"
        ]
    },
   "jvm_platforms": {
        "platforms": {
            "java6": {
                "source_level": "1.6",
                "args": [],
                "target_level": "1.6"
            }
        },
        "default_platform": "java6"
    },
    "python_setup": {
        "interpreters": {
            "CPython-2.7.10": {
                "binary": "/Users/user/pants/build-support/pants_dev_deps.venv/bin/python2.7",
                "chroot": "/Users/user/pants/.pants.d/python-setup/chroots/e8da2c200f36ca0a1b8a60c12590a59209250b1a"
            }
        },
        "default_interpreter": "CPython-2.7.10"
    },
    "targets": {
        "examples/tests/java/org/pantsbuild/example/usethrift:usethrift": {
            "is_code_gen": false,
            "excludes": [],
            "target_type": "TEST",
            "libraries": [
                "junit:junit:4.12",
                "org.hamcrest:hamcrest-core:1.3",
                "junit:junit:latest.integration"
            ],
            "platform": "java6",
            "pants_target_type": "java_tests",
            "globs": {
                "globs": [
                    "examples/tests/java/org/pantsbuild/example/usethrift/UseThriftTest.java"
                ]
            },
            "targets": [
                "3rdparty:junit",
                "examples/src/thrift/org/pantsbuild/example/distance:distance-java",
                "examples/src/thrift/org/pantsbuild/example/precipitation:precipitation-java",
                ".pants.d/gen/thrift/isolated/examples.src.thrift.org.pantsbuild.example.distance.distance-java:examples.src.thrift.org.pantsbuild.example.distance.distance-java",
                ".pants.d/gen/thrift/isolated/examples.src.thrift.org.pantsbuild.example.precipitation.precipitation-java:examples.src.thrift.org.pantsbuild.example.precipitation.precipitation-java"
            ],
            "roots": [
                {
                    "source_root": "/Users/user/pants/examples/tests/java/org/pantsbuild/example/usethrift",
                    "package_prefix": "org.pantsbuild.example.usethrift"
                }
            ]
        },
        "examples/src/python/example/hello/greet:greet": {
            "is_code_gen": false,
            "python_interpreter": "CPython-2.7.10",
            "target_type": "SOURCE",
            "libraries": [],
            "pants_target_type": "python_library",
            "globs": {
                "globs": [
                    "examples/src/python/example/hello/greet/*.py"
                ]
            },
            "targets": [
                "3rdparty/python:ansicolors"
            ],
            "roots": [
                {
                    "source_root": "/Users/user/pants/examples/src/python/example/hello/greet",
                    "package_prefix": "example.hello.greet"
                }
            ]
        },

        ...
   }
}
```


# Export Format Changes

## 1.0.3

Added information about jdk settings

## 1.0.2

Handle jars with classifiers

## 1.0.1

Information about excludes

## 1.0.0

Initial Version
