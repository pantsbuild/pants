// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fs::File;
use std::io::Write;
use std::path::Path;

// NOTE: This method is not in the `src/rust/engine/testutil` crate because that will cause a cyclic
// dependency between `fs` and `testutil` due to `testutil` using types from this `fs` crate in its
// public interface.

pub(crate) fn make_file(path: &Path, contents: &[u8], mode: u32) {
    let mut file = File::create(path).unwrap();
    file.write_all(contents).unwrap();

    #[cfg(not(target_os = "windows"))]
    {
        use std::os::unix::fs::PermissionsExt;

        let mut permissions = std::fs::metadata(path).unwrap().permissions();
        permissions.set_mode(mode);
        file.set_permissions(permissions).unwrap();
    }
}
