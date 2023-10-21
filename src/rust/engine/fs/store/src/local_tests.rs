// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::local::ByteStore;
use crate::{EntryType, LocalOptions, ShrinkBehavior};

use std::path::Path;
use std::time::Duration;

use bytes::{Buf, BufMut, Bytes, BytesMut};
use hashing::{Digest, Fingerprint};
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory};
use tokio::time::sleep;
use walkdir::WalkDir;

// Store bytes using both the one-pass and two-pass APIs, and ensure identical results.
async fn assert_store_bytes(
    store: ByteStore,
    entry_type: EntryType,
    bytes: Bytes,
    expected_digest: Digest,
) {
    let digest = store
        .store(entry_type, false, true, move || Ok(bytes.clone().reader()))
        .await
        .unwrap();
    assert_eq!(expected_digest, digest);
}

#[tokio::test]
async fn save_file() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();
    assert_store_bytes(
        new_store(dir.path()),
        EntryType::File,
        testdata.bytes(),
        testdata.digest(),
    )
    .await;
}

#[tokio::test]
async fn save_file_is_idempotent() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();
    assert_store_bytes(
        new_store(dir.path()),
        EntryType::File,
        testdata.bytes(),
        testdata.digest(),
    )
    .await;
    assert_store_bytes(
        new_store(dir.path()),
        EntryType::File,
        testdata.bytes(),
        testdata.digest(),
    )
    .await;
}

#[tokio::test]
async fn roundtrip_file() {
    let testdata = TestData::roland();
    let dir = TempDir::new().unwrap();

    let store = new_store(dir.path());
    let hash = prime_store_with_file_bytes(&store, testdata.bytes()).await;
    assert_eq!(
        load_file_bytes(&store, hash).await,
        Ok(Some(testdata.bytes()))
    );
}

#[tokio::test]
async fn missing_file() {
    let dir = TempDir::new().unwrap();
    assert_eq!(
        load_file_bytes(&new_store(dir.path()), TestData::roland().digest()).await,
        Ok(None)
    );
}

#[tokio::test]
async fn record_and_load_directory_proto() {
    let dir = TempDir::new().unwrap();
    let testdir = TestDirectory::containing_roland();

    assert_store_bytes(
        new_store(dir.path()),
        EntryType::Directory,
        testdir.bytes(),
        testdir.digest(),
    )
    .await;

    assert_eq!(
        load_directory_proto_bytes(&new_store(dir.path()), testdir.digest()).await,
        Ok(Some(testdir.bytes()))
    );
}

#[tokio::test]
async fn missing_directory() {
    let dir = TempDir::new().unwrap();
    let testdir = TestDirectory::containing_roland();

    assert_eq!(
        load_directory_proto_bytes(&new_store(dir.path()), testdir.digest()).await,
        Ok(None)
    );
}

#[tokio::test]
async fn file_is_not_directory_proto() {
    let dir = TempDir::new().unwrap();
    let testdata = TestData::roland();

    assert_store_bytes(
        new_store(dir.path()),
        EntryType::File,
        testdata.bytes(),
        testdata.digest(),
    )
    .await;

    assert_eq!(
        load_directory_proto_bytes(&new_store(dir.path()), testdata.digest()).await,
        Ok(None)
    );
}

#[tokio::test]
async fn garbage_collect_nothing_to_do() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    let bytes = Bytes::from("0123456789");
    let fingerprint = Fingerprint::from_hex_string(
        "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
    )
    .unwrap();
    let digest = Digest::new(fingerprint, 10);

    store
        .store_bytes(EntryType::File, fingerprint, bytes.clone(), false)
        .await
        .expect("Error storing");
    store
        .shrink(10, ShrinkBehavior::Fast)
        .expect("Error shrinking");
    assert_eq!(
        load_bytes(&store, EntryType::File, digest).await,
        Ok(Some(bytes))
    );
}

#[tokio::test]
async fn garbage_collect_nothing_to_do_with_lease() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    let bytes = Bytes::from("0123456789");
    let file_fingerprint = Fingerprint::from_hex_string(
        "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
    )
    .unwrap();
    let file_digest = Digest::new(file_fingerprint, 10);
    store
        .store_bytes(EntryType::File, file_fingerprint, bytes.clone(), false)
        .await
        .expect("Error storing");
    store
        .lease_all(vec![(file_digest, EntryType::File)].into_iter())
        .await
        .expect("Error leasing");
    store
        .shrink(10, ShrinkBehavior::Fast)
        .expect("Error shrinking");
    assert_eq!(
        load_bytes(&store, EntryType::File, file_digest).await,
        Ok(Some(bytes))
    );
}

#[tokio::test]
async fn garbage_collect_expired() {
    let lease_time = Duration::from_secs(1);
    let dir = TempDir::new().unwrap();
    let store = new_store_with_lease_time(dir.path(), lease_time);
    let bytes = Bytes::from("0123456789");
    let file_fingerprint = Fingerprint::from_hex_string(
        "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
    )
    .unwrap();
    let file_len = 10;
    let file_digest = Digest::new(file_fingerprint, file_len);

    // Store something (in a store with a shortened lease). Confirm that it hasn't immediately
    // expired, and then wait for it to expire.
    store
        .store_bytes(EntryType::File, file_fingerprint, bytes.clone(), true)
        .await
        .expect("Error storing");
    assert_eq!(
        file_len,
        store
            .shrink(0, ShrinkBehavior::Fast)
            .expect("Error shrinking"),
    );
    assert_eq!(
        load_bytes(&store, EntryType::File, file_digest).await,
        Ok(Some(bytes))
    );

    // Wait for it to expire.
    sleep(lease_time * 2).await;
    assert_eq!(
        0,
        store
            .shrink(0, ShrinkBehavior::Fast)
            .expect("Should have cleared expired lease")
    );
}

#[tokio::test]
async fn garbage_collect_remove_one_of_two_files_no_leases() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    let bytes_1 = Bytes::from("0123456789");
    let fingerprint_1 = Fingerprint::from_hex_string(
        "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
    )
    .unwrap();
    let digest_1 = Digest::new(fingerprint_1, 10);
    let bytes_2 = Bytes::from("9876543210");
    let fingerprint_2 = Fingerprint::from_hex_string(
        "7619ee8cea49187f309616e30ecf54be072259b43760f1f550a644945d5572f2",
    )
    .unwrap();
    let digest_2 = Digest::new(fingerprint_2, 10);
    store
        .store_bytes(EntryType::File, fingerprint_1, bytes_1.clone(), false)
        .await
        .expect("Error storing");
    store
        .store_bytes(EntryType::File, fingerprint_2, bytes_2.clone(), false)
        .await
        .expect("Error storing");
    store
        .shrink(10, ShrinkBehavior::Fast)
        .expect("Error shrinking");
    let mut entries = Vec::new();
    entries.push(
        load_bytes(&store, EntryType::File, digest_1)
            .await
            .expect("Error loading bytes"),
    );
    entries.push(
        load_bytes(&store, EntryType::File, digest_2)
            .await
            .expect("Error loading bytes"),
    );
    assert_eq!(
        1,
        entries.iter().filter(|maybe| maybe.is_some()).count(),
        "Want one Some but got: {entries:?}"
    );
}

#[tokio::test]
async fn garbage_collect_remove_both_files_no_leases() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    let bytes_1 = Bytes::from("0123456789");
    let fingerprint_1 = Fingerprint::from_hex_string(
        "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
    )
    .unwrap();
    let digest_1 = Digest::new(fingerprint_1, 10);
    let bytes_2 = Bytes::from("9876543210");
    let fingerprint_2 = Fingerprint::from_hex_string(
        "7619ee8cea49187f309616e30ecf54be072259b43760f1f550a644945d5572f2",
    )
    .unwrap();
    let digest_2 = Digest::new(fingerprint_2, 10);
    store
        .store_bytes(EntryType::File, fingerprint_1, bytes_1.clone(), false)
        .await
        .expect("Error storing");
    store
        .store_bytes(EntryType::File, fingerprint_2, bytes_2.clone(), false)
        .await
        .expect("Error storing");
    store
        .shrink(1, ShrinkBehavior::Fast)
        .expect("Error shrinking");
    assert_eq!(
        load_bytes(&store, EntryType::File, digest_1).await,
        Ok(None),
        "Should have garbage collected {fingerprint_1:?}"
    );
    assert_eq!(
        load_bytes(&store, EntryType::File, digest_2).await,
        Ok(None),
        "Should have garbage collected {fingerprint_2:?}"
    );
}

#[tokio::test]
async fn garbage_collect_remove_one_of_two_directories_no_leases() {
    let dir = TempDir::new().unwrap();

    let testdir = TestDirectory::containing_roland();
    let other_testdir = TestDirectory::containing_dnalor();

    let store = new_store(dir.path());
    store
        .store_bytes(
            EntryType::Directory,
            testdir.fingerprint(),
            testdir.bytes(),
            false,
        )
        .await
        .expect("Error storing");
    store
        .store_bytes(
            EntryType::Directory,
            other_testdir.fingerprint(),
            other_testdir.bytes(),
            false,
        )
        .await
        .expect("Error storing");
    store
        .shrink(84, ShrinkBehavior::Fast)
        .expect("Error shrinking");
    let mut entries = Vec::new();
    entries.push(
        load_bytes(&store, EntryType::Directory, testdir.digest())
            .await
            .expect("Error loading bytes"),
    );
    entries.push(
        load_bytes(&store, EntryType::Directory, other_testdir.digest())
            .await
            .expect("Error loading bytes"),
    );
    assert_eq!(
        1,
        entries.iter().filter(|maybe| maybe.is_some()).count(),
        "Want one Some but got: {entries:?}"
    );
}

#[tokio::test]
async fn garbage_collect_remove_file_with_leased_directory() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());

    let testdir = TestDirectory::containing_roland();
    let testdata = TestData::forty_chars();

    store
        .store_bytes(
            EntryType::Directory,
            testdir.fingerprint(),
            testdir.bytes(),
            true,
        )
        .await
        .expect("Error storing");

    store
        .store_bytes(
            EntryType::File,
            testdata.fingerprint(),
            testdata.bytes(),
            false,
        )
        .await
        .expect("Error storing");

    store
        .shrink(80, ShrinkBehavior::Fast)
        .expect("Error shrinking");

    assert_eq!(
        load_bytes(&store, EntryType::File, testdata.digest()).await,
        Ok(None),
        "File was present when it should've been garbage collected"
    );
    assert_eq!(
        load_bytes(&store, EntryType::Directory, testdir.digest()).await,
        Ok(Some(testdir.bytes())),
        "Directory was missing despite lease"
    );
}

#[tokio::test]
async fn garbage_collect_remove_file_while_leased_file() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());

    let testdir = TestDirectory::containing_roland();

    store
        .store_bytes(
            EntryType::Directory,
            testdir.fingerprint(),
            testdir.bytes(),
            false,
        )
        .await
        .expect("Error storing");
    let forty_chars = TestData::forty_chars();
    store
        .store_bytes(
            EntryType::File,
            forty_chars.fingerprint(),
            forty_chars.bytes(),
            true,
        )
        .await
        .expect("Error storing");

    store
        .shrink(80, ShrinkBehavior::Fast)
        .expect("Error shrinking");

    assert_eq!(
        load_bytes(&store, EntryType::File, forty_chars.digest()).await,
        Ok(Some(forty_chars.bytes())),
        "File was missing despite lease"
    );
    assert_eq!(
        load_bytes(&store, EntryType::Directory, testdir.digest()).await,
        Ok(None),
        "Directory was present when it should've been garbage collected"
    );
}

#[tokio::test]
async fn garbage_collect_fail_because_too_many_leases() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());

    let testdir = TestDirectory::containing_roland();
    let forty_chars = TestData::forty_chars();
    let roland = TestData::roland();

    store
        .store_bytes(
            EntryType::Directory,
            testdir.fingerprint(),
            testdir.bytes(),
            true,
        )
        .await
        .expect("Error storing");
    store
        .store_bytes(
            EntryType::File,
            forty_chars.fingerprint(),
            forty_chars.bytes(),
            true,
        )
        .await
        .expect("Error storing");
    store
        .store_bytes(EntryType::File, roland.fingerprint(), roland.bytes(), false)
        .await
        .expect("Error storing");

    assert_eq!(store.shrink(80, ShrinkBehavior::Fast), Ok(164));

    assert_eq!(
        load_bytes(&store, EntryType::File, forty_chars.digest()).await,
        Ok(Some(forty_chars.bytes())),
        "Leased file should still be present"
    );
    assert_eq!(
        load_bytes(&store, EntryType::Directory, testdir.digest()).await,
        Ok(Some(testdir.bytes())),
        "Leased directory should still be present"
    );
    // Whether the unleased file is present is undefined.
}

async fn write_one_meg(store: &ByteStore, byte: u8) {
    let mut bytes = BytesMut::with_capacity(1024 * 1024);
    for _ in 0..1024 * 1024 {
        bytes.put_u8(byte);
    }
    let fingerprint = Digest::of_bytes(&bytes).hash;
    store
        .store_bytes(EntryType::File, fingerprint, bytes.freeze(), false)
        .await
        .expect("Error storing");
}

#[tokio::test]
async fn garbage_collect_and_compact() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());

    write_one_meg(&store, b'0').await;

    write_one_meg(&store, b'1').await;

    let size = get_directory_size(dir.path());
    assert!(
        size >= 2 * 1024 * 1024,
        "Expect size to be at least 2MB but was {size}"
    );

    store
        .shrink(1024 * 1024, ShrinkBehavior::Compact)
        .expect("Error shrinking");

    let size = get_directory_size(dir.path());
    assert!(
        size < 2 * 1024 * 1024,
        "Expect size to be less than 2MB but was {size}"
    );
}

#[tokio::test]
async fn entry_type_for_file() {
    let testdata = TestData::roland();
    let testdir = TestDirectory::containing_roland();
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    store
        .store_bytes(
            EntryType::Directory,
            testdir.fingerprint(),
            testdir.bytes(),
            false,
        )
        .await
        .expect("Error storing");
    prime_store_with_file_bytes(&store, testdata.bytes()).await;
    assert_eq!(
        store.entry_type(testdata.fingerprint()).await,
        Ok(Some(EntryType::File))
    )
}

#[tokio::test]
async fn entry_type_for_directory() {
    let testdata = TestData::roland();
    let testdir = TestDirectory::containing_roland();
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    store
        .store_bytes(
            EntryType::Directory,
            testdir.fingerprint(),
            testdir.bytes(),
            false,
        )
        .await
        .expect("Error storing");
    prime_store_with_file_bytes(&store, testdata.bytes()).await;
    assert_eq!(
        store.entry_type(testdir.fingerprint()).await,
        Ok(Some(EntryType::Directory))
    )
}

#[tokio::test]
async fn entry_type_for_missing() {
    let testdata = TestData::roland();
    let testdir = TestDirectory::containing_roland();
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    store
        .store_bytes(
            EntryType::Directory,
            testdir.fingerprint(),
            testdir.bytes(),
            false,
        )
        .await
        .expect("Error storing");
    prime_store_with_file_bytes(&store, testdata.bytes()).await;
    assert_eq!(
        store
            .entry_type(TestDirectory::recursive().fingerprint())
            .await,
        Ok(None)
    )
}

#[tokio::test]
async fn empty_file_is_known() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    let empty_file = TestData::empty();
    assert_eq!(
        store
            .load_bytes_with(EntryType::File, empty_file.digest(), |b| {
                Bytes::copy_from_slice(b)
            })
            .await,
        Ok(Some(empty_file.bytes())),
    )
}

#[tokio::test]
async fn empty_directory_is_known() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    let empty_dir = TestDirectory::empty();
    assert_eq!(
        store
            .load_bytes_with(EntryType::Directory, empty_dir.digest(), |b| {
                Bytes::copy_from_slice(b)
            })
            .await,
        Ok(Some(empty_dir.bytes())),
    )
}

#[tokio::test]
async fn all_digests() {
    let dir = TempDir::new().unwrap();
    let store = new_store(dir.path());
    let digest = prime_store_with_file_bytes(&store, TestData::roland().bytes()).await;
    assert_eq!(Ok(vec![digest]), store.all_digests(EntryType::File));
}

pub fn new_store<P: AsRef<Path>>(dir: P) -> ByteStore {
    ByteStore::new(task_executor::Executor::new(), dir).unwrap()
}

pub fn new_store_with_lease_time<P: AsRef<Path>>(dir: P, lease_time: Duration) -> ByteStore {
    ByteStore::new_with_options(
        task_executor::Executor::new(),
        dir,
        LocalOptions {
            lease_time,
            ..LocalOptions::default()
        },
    )
    .unwrap()
}

pub async fn load_file_bytes(store: &ByteStore, digest: Digest) -> Result<Option<Bytes>, String> {
    load_bytes(store, EntryType::File, digest).await
}

pub async fn load_directory_proto_bytes(
    store: &ByteStore,
    digest: Digest,
) -> Result<Option<Bytes>, String> {
    load_bytes(store, EntryType::Directory, digest).await
}

pub async fn load_bytes(
    store: &ByteStore,
    entry_type: EntryType,
    digest: Digest,
) -> Result<Option<Bytes>, String> {
    store
        .load_bytes_with(entry_type, digest, Bytes::copy_from_slice)
        .await
}

async fn prime_store_with_file_bytes(store: &ByteStore, bytes: Bytes) -> Digest {
    let digest = Digest::of_bytes(&bytes);
    store
        .store_bytes(EntryType::File, digest.hash, bytes, false)
        .await
        .expect("Error storing file bytes");
    digest
}

fn get_directory_size(path: &Path) -> usize {
    let mut len: usize = 0;
    for entry in WalkDir::new(path) {
        len += entry
            .expect("Error walking directory")
            .metadata()
            .expect("Error reading metadata")
            .len() as usize;
    }
    len
}
