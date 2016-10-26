# RPM Builder Plugin for Pants

This plugin build RPM packages for Red Hat Linux and similar distributions such as
CentOS and Fedora.

This README assumes a decent familiarity with building RPM packages using the `rpmbuild`
tool. The default configuration of the plugin currently assumes you are just building
for CentOS 6 or 7.

## Targets

The main target type is the `rpm_package` target. This target points at the RPM .spec file to
use and the local and remote sources to provide to RPM in the `SOURCES` directory.
(Note: RPM differentiates between "sources" and "patches" in the spec file. For purposes of
the `rpm_package` target, both "sources" and "patches" are provided to the Pants plugin via the
`sources` or `remote_sources` attributes of the `rpm_package` target.)

The attributes of the `rpm_package` target are:

| Attribute | Purpose | Required? |
----------------------------------
| name | Name of the target | |
| spec | Relative path to the RPM spec file. File is copied to RPM `SPECS` directory | Yes |
| sources | Relative path to files to copy into the RPM `SOURCES` directory | |
| remote_sources | URLs to files to download and copy into the RPM `SOURCES` directory. Useful for large files stored on a file server | |
| defines | Dictionary of RPM defines to set on the `rpmbuild` command-line. | |

## Execution

Using the example BUILD file and spec provided with this plugin's source code, build the
example golang RPM via this command:

```
./pants rpmbuild contrib/rpmbuild/examples:golang
```

The plugin would build a Docker image with the necessary files and then execute it to build the RPMS.
The resulting RPMs will be extracted from the container and placed under the `dist/rpmbuild` directory
tree. Binary RPMs are under `dist/rpmbuild/RPMS`, and source RPMS ("SRPMS") are under
`dist/rpmbuild/SRPMS`.

You can change the platform for which you are building by using the `--rpmbuild-platform` parameter.
Set the `platform_metadata` paramater to define a mapping between platform names and metadata about
each platform. (Currently, only a `base` attribute is supported for each platform to define the 
Docker base image for the image used to build the RPMS.)