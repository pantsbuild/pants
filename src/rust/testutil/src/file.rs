// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::io::Read;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use tokio::io::{AsyncSeekExt, AsyncWriteExt};

pub fn list_dir(path: &Path) -> Vec<String> {
    let mut v: Vec<_> = std::fs::read_dir(path)
        .unwrap_or_else(|err| panic!("Listing dir {path:?}: {err:?}"))
        .map(|entry| {
            entry
                .expect("Error reading entry")
                .file_name()
                .to_string_lossy()
                .to_string()
        })
        .collect();
    v.sort();
    v
}

pub fn contents(path: &Path) -> bytes::Bytes {
    let mut contents = Vec::new();
    std::fs::File::open(path)
        .and_then(|mut f| f.read_to_end(&mut contents))
        .expect("Error reading file");
    bytes::Bytes::from(contents)
}

#[cfg(unix)]
pub fn is_executable(path: &Path) -> bool {
    std::fs::metadata(path)
        .map(|meta| meta.permissions().mode() & 0o100 == 0o100)
        .unwrap_or(false)
}

/// Windows has no executable permission bit, so (as in `fs::WinFS`) a file is executable if it
/// exists and its extension is one of a fixed list, matched case-insensitively.
#[cfg(windows)]
pub fn is_executable(path: &Path) -> bool {
    std::fs::metadata(path).is_ok_and(|meta| meta.is_file())
        && path
            .extension()
            .and_then(|ext| ext.to_str())
            .is_some_and(|ext| {
                fs::EXECUTABLE_EXTENSIONS
                    .iter()
                    .any(|exe_ext| ext.eq_ignore_ascii_case(exe_ext))
            })
}

pub async fn mk_tempfile(contents: Option<&[u8]>) -> tokio::fs::File {
    let file = tokio::task::spawn_blocking(tempfile::tempfile)
        .await
        .unwrap()
        .unwrap();
    let mut file = tokio::fs::File::from_std(file);

    if let Some(contents) = contents {
        file.write_all(contents).await.unwrap();
        file.rewind().await.unwrap();
    }

    file
}
