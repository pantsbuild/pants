// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::env;
use std::ops::Deref;
use std::path::{Path, PathBuf};

use log::debug;

#[derive(Debug)]
pub struct BuildRoot(PathBuf);

impl BuildRoot {
    const SENTINEL_FILES: &'static [&'static str] = &["pants.toml", "BUILDROOT", "BUILD_ROOT"];

    pub fn find() -> Result<BuildRoot, String> {
        let cwd = env::current_dir().map_err(|e| format!("Failed to determine $CWD: {e}"))?;
        Self::find_from(&cwd)
    }

    pub(crate) fn find_from(start: &Path) -> Result<BuildRoot, String> {
        let mut build_root = start;
        loop {
            for sentinel in Self::SENTINEL_FILES {
                let sentinel_path = build_root.join(sentinel);
                if !sentinel_path.exists() {
                    continue;
                }
                let sentinel_path_metadata = sentinel_path.metadata().map_err(|e| {
                    format!(
                        "\
            Failed to read metadata for {path} to determine if is a build root sentinel file: {err}\
            ",
                        path = sentinel_path.display(),
                        err = e
                    )
                })?;
                if sentinel_path_metadata.is_file() {
                    let root = BuildRoot(build_root.to_path_buf());
                    debug!("Found {:?} starting search from {}.", root, start.display());
                    return Ok(root);
                }
            }

            build_root = build_root.parent().ok_or(format!(
                "\
          No build root detected for the current directory of {cwd}. Pants detects the build root \
          by looking for at least one file from {sentinel_files} in the cwd and its ancestors. If \
          you have none of these files, you can create an empty file in your build root.\
          ",
                cwd = start.display(),
                sentinel_files = Self::SENTINEL_FILES.join(", ")
            ))?;
        }
    }
}

impl Deref for BuildRoot {
    type Target = PathBuf;

    fn deref(&self) -> &PathBuf {
        &self.0
    }
}
