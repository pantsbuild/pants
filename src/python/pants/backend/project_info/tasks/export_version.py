# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# FORMAT_VERSION_NUMBER: Version number for identifying the export file format output. This
# number is shared between `export` and `export-dep-as-jar` task, so it should be changed
# when either task changes the output format.
#
# Major Version 1.x.x : Increment this field when there is a major format change
# Minor Version x.1.x : Increment this field when there is a minor change that breaks backward
#   compatibility for an existing field or a field is removed.
# Patch version x.x.1 : Increment this field when a minor format change that just adds information
#   that an application can safely ignore.
#
# Note format changes in src/docs/export.md and update the Changelog section.
#
DEFAULT_EXPORT_VERSION = "1.1.0"
