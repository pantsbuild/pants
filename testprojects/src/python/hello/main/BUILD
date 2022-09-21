# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(name="lib")
pex_binary(name="main", entry_point="main.py")

file(name="main_file", source="main.py")
archive(name="archive_zip", format="zip", files=[":main_file"])
archive(name="archive_tar", format="tar", files=[":main_file"])
archive(name="archive_targz", format="tar.gz", files=[":main_file"])
