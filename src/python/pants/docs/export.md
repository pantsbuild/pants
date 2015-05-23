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

The following is an abbreviated export file from the command in the pants repo:

`pants export examples/tests/java/org/pantsbuild/example/usethrift:usethrift`


```
{

  "version": "1.0.0",
  "libraries": {
        "org.hamcrest:hamcrest-core:1.3": {
            "default": "/Users/zundel/.ivy2/pants/org.hamcrest/hamcrest-core/jars/hamcrest-core-1.3.jar"
        },
        ...
  }
  "targets": {
        "examples/tests/java/org/pantsbuild/example/usethrift:usethrift": {
            "is_code_gen": false,
            "target_type": "TEST",
            "libraries": [
                "junit:junit:4.12",
                "org.hamcrest:hamcrest-core:1.3"
            ],
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
                ".pants.d/gen/thrift/combined/gen-java:examples.src.thrift.org.pantsbuild.example.precipitation.precipitation-java",
                ".pants.d/gen/thrift/combined/gen-java:examples.src.thrift.org.pantsbuild.example.distance.distance-java"
            ],
            "roots": [
                {
                    "source_root": "/Users/zundel/Src/pants/examples/tests/java/org/pantsbuild/example/usethrift",
                    "package_prefix": "org.pantsbuild.example.usethrift"
                }
            ]
        },
        ...
   }
```


# Export Format Changes

## 1.0.1

Information about excludes

## 1.0.0

Initial Version
