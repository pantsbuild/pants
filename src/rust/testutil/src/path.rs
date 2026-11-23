// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::env;
use std::path::{Path, PathBuf};

pub fn find_bash() -> String {
    which("bash")
        .expect("No bash on PATH")
        .to_str()
        .expect("Path to bash not unicode")
        .to_owned()
}

pub fn which(executable: &str) -> Option<PathBuf> {
    // On Windows, executables carry an extension, so look up a bare name like `bash` as `bash.exe`.
    let executable = if cfg!(windows) && Path::new(executable).extension().is_none() {
        format!("{executable}.exe")
    } else {
        executable.to_owned()
    };
    if let Some(paths) = env::var_os("PATH") {
        for path in env::split_paths(&paths) {
            let executable_path = path.join(&executable);
            if executable_path.exists() && crate::file::is_executable(&executable_path) {
                return Some(executable_path);
            }
        }
    }
    None
}
