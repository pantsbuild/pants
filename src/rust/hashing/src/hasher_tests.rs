// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use tempfile::TempDir;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

#[test]
fn hashes() {
    let mut src = "meep".as_bytes();

    let dst = Vec::with_capacity(10);
    let mut hasher = super::WriterHasher::new(dst);
    assert_eq!(std::io::copy(&mut src, &mut hasher).unwrap(), 4);
    let want = (
        super::Digest::new(
            super::Fingerprint::from_hex_string(
                "23e92dfba8fb0c93cfba31ad2962b4e35a47054296d1d375d7f7e13e0185de7a",
            )
            .unwrap(),
            4,
        ),
        "meep".as_bytes().to_vec(),
    );
    assert_eq!(hasher.finish(), want);
}

#[tokio::test]
async fn async_hashes() {
    let tmpdir = TempDir::new().unwrap();
    let tmppath = tmpdir.path().to_owned();
    let mut src_file = tokio::fs::File::create(tmppath.join("src")).await.unwrap();
    src_file.write_all(b"meep").await.unwrap();
    let mut src_file = tokio::fs::File::open(tmppath.join("src")).await.unwrap();
    let mut dest_file = tokio::fs::File::create(tmppath.join("dest")).await.unwrap();

    let mut hasher = super::WriterHasher::new(&mut dest_file);
    assert_eq!(
        tokio::io::copy(&mut src_file, &mut hasher).await.unwrap(),
        4
    );
    let want = super::Digest::new(
        super::Fingerprint::from_hex_string(
            "23e92dfba8fb0c93cfba31ad2962b4e35a47054296d1d375d7f7e13e0185de7a",
        )
        .unwrap(),
        4,
    );
    assert_eq!(hasher.finish().0, want);
    let mut contents = vec![];
    tokio::fs::File::open(tmppath.join("dest"))
        .await
        .unwrap()
        .read_to_end(&mut contents)
        .await
        .unwrap();
    assert_eq!("meep".as_bytes().to_vec(), contents);
}
