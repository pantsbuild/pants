use crate::local::ByteStore;
use crate::tests::block_on;
use crate::{EntryType, ShrinkBehavior};
use bytes::{BufMut, Bytes, BytesMut};
use hashing::{Digest, Fingerprint};
use std::convert::From;
use std::path::Path;
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory};
use walkdir::WalkDir;

#[test]
fn save_file() {
  let dir = TempDir::new().unwrap();

  let testdata = TestData::roland();
  assert_eq!(
    block_on(new_store(dir.path()).store_bytes(EntryType::File, testdata.bytes(), false,)),
    Ok(testdata.digest())
  );
}

#[test]
fn save_file_is_idempotent() {
  let dir = TempDir::new().unwrap();

  let testdata = TestData::roland();
  block_on(new_store(dir.path()).store_bytes(EntryType::File, testdata.bytes(), false)).unwrap();
  assert_eq!(
    block_on(new_store(dir.path()).store_bytes(EntryType::File, testdata.bytes(), false,)),
    Ok(testdata.digest())
  );
}

#[test]
fn roundtrip_file() {
  let testdata = TestData::roland();
  let dir = TempDir::new().unwrap();

  let store = new_store(dir.path());
  let hash = prime_store_with_file_bytes(&store, testdata.bytes());
  assert_eq!(load_file_bytes(&store, hash), Ok(Some(testdata.bytes())));
}

#[test]
fn missing_file() {
  let dir = TempDir::new().unwrap();
  assert_eq!(
    load_file_bytes(&new_store(dir.path()), TestData::roland().digest()),
    Ok(None)
  );
}

#[test]
fn record_and_load_directory_proto() {
  let dir = TempDir::new().unwrap();
  let testdir = TestDirectory::containing_roland();

  assert_eq!(
    block_on(new_store(dir.path()).store_bytes(EntryType::Directory, testdir.bytes(), false,)),
    Ok(testdir.digest())
  );

  assert_eq!(
    load_directory_proto_bytes(&new_store(dir.path()), testdir.digest()),
    Ok(Some(testdir.bytes()))
  );
}

#[test]
fn missing_directory() {
  let dir = TempDir::new().unwrap();
  let testdir = TestDirectory::containing_roland();

  assert_eq!(
    load_directory_proto_bytes(&new_store(dir.path()), testdir.digest()),
    Ok(None)
  );
}

#[test]
fn file_is_not_directory_proto() {
  let dir = TempDir::new().unwrap();
  let testdata = TestData::roland();

  block_on(new_store(dir.path()).store_bytes(EntryType::File, testdata.bytes(), false)).unwrap();

  assert_eq!(
    load_directory_proto_bytes(&new_store(dir.path()), testdata.digest()),
    Ok(None)
  );
}

#[test]
fn garbage_collect_nothing_to_do() {
  let dir = TempDir::new().unwrap();
  let store = new_store(dir.path());
  let bytes = Bytes::from("0123456789");
  block_on(store.store_bytes(EntryType::File, bytes.clone(), false)).expect("Error storing");
  store
    .shrink(10, ShrinkBehavior::Fast)
    .expect("Error shrinking");
  assert_eq!(
    load_bytes(
      &store,
      EntryType::File,
      Digest(
        Fingerprint::from_hex_string(
          "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
        )
        .unwrap(),
        10
      )
    ),
    Ok(Some(bytes))
  );
}

#[test]
fn garbage_collect_nothing_to_do_with_lease() {
  let dir = TempDir::new().unwrap();
  let store = new_store(dir.path());
  let bytes = Bytes::from("0123456789");
  block_on(store.store_bytes(EntryType::File, bytes.clone(), false)).expect("Error storing");
  let file_fingerprint = Fingerprint::from_hex_string(
    "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
  )
  .unwrap();
  let file_digest = Digest(file_fingerprint, 10);
  store
    .lease_all(vec![file_digest].iter())
    .expect("Error leasing");
  store
    .shrink(10, ShrinkBehavior::Fast)
    .expect("Error shrinking");
  assert_eq!(
    load_bytes(&store, EntryType::File, file_digest),
    Ok(Some(bytes))
  );
}

#[test]
fn garbage_collect_remove_one_of_two_files_no_leases() {
  let dir = TempDir::new().unwrap();
  let store = new_store(dir.path());
  let bytes_1 = Bytes::from("0123456789");
  let fingerprint_1 = Fingerprint::from_hex_string(
    "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
  )
  .unwrap();
  let digest_1 = Digest(fingerprint_1, 10);
  let bytes_2 = Bytes::from("9876543210");
  let fingerprint_2 = Fingerprint::from_hex_string(
    "7619ee8cea49187f309616e30ecf54be072259b43760f1f550a644945d5572f2",
  )
  .unwrap();
  let digest_2 = Digest(fingerprint_2, 10);
  block_on(store.store_bytes(EntryType::File, bytes_1.clone(), false)).expect("Error storing");
  block_on(store.store_bytes(EntryType::File, bytes_2.clone(), false)).expect("Error storing");
  store
    .shrink(10, ShrinkBehavior::Fast)
    .expect("Error shrinking");
  let mut entries = Vec::new();
  entries.push(load_bytes(&store, EntryType::File, digest_1).expect("Error loading bytes"));
  entries.push(load_bytes(&store, EntryType::File, digest_2).expect("Error loading bytes"));
  assert_eq!(
    1,
    entries.iter().filter(|maybe| maybe.is_some()).count(),
    "Want one Some but got: {:?}",
    entries
  );
}

#[test]
fn garbage_collect_remove_both_files_no_leases() {
  let dir = TempDir::new().unwrap();
  let store = new_store(dir.path());
  let bytes_1 = Bytes::from("0123456789");
  let fingerprint_1 = Fingerprint::from_hex_string(
    "84d89877f0d4041efb6bf91a16f0248f2fd573e6af05c19f96bedb9f882f7882",
  )
  .unwrap();
  let digest_1 = Digest(fingerprint_1, 10);
  let bytes_2 = Bytes::from("9876543210");
  let fingerprint_2 = Fingerprint::from_hex_string(
    "7619ee8cea49187f309616e30ecf54be072259b43760f1f550a644945d5572f2",
  )
  .unwrap();
  let digest_2 = Digest(fingerprint_2, 10);
  block_on(store.store_bytes(EntryType::File, bytes_1.clone(), false)).expect("Error storing");
  block_on(store.store_bytes(EntryType::File, bytes_2.clone(), false)).expect("Error storing");
  store
    .shrink(1, ShrinkBehavior::Fast)
    .expect("Error shrinking");
  assert_eq!(
    load_bytes(&store, EntryType::File, digest_1),
    Ok(None),
    "Should have garbage collected {:?}",
    fingerprint_1
  );
  assert_eq!(
    load_bytes(&store, EntryType::File, digest_2),
    Ok(None),
    "Should have garbage collected {:?}",
    fingerprint_2
  );
}

#[test]
fn garbage_collect_remove_one_of_two_directories_no_leases() {
  let dir = TempDir::new().unwrap();

  let testdir = TestDirectory::containing_roland();
  let other_testdir = TestDirectory::containing_dnalor();

  let store = new_store(dir.path());
  block_on(store.store_bytes(EntryType::Directory, testdir.bytes(), false)).expect("Error storing");
  block_on(store.store_bytes(EntryType::Directory, other_testdir.bytes(), false))
    .expect("Error storing");
  store
    .shrink(80, ShrinkBehavior::Fast)
    .expect("Error shrinking");
  let mut entries = Vec::new();
  entries
    .push(load_bytes(&store, EntryType::Directory, testdir.digest()).expect("Error loading bytes"));
  entries.push(
    load_bytes(&store, EntryType::Directory, other_testdir.digest()).expect("Error loading bytes"),
  );
  assert_eq!(
    1,
    entries.iter().filter(|maybe| maybe.is_some()).count(),
    "Want one Some but got: {:?}",
    entries
  );
}

#[test]
fn garbage_collect_remove_file_with_leased_directory() {
  let dir = TempDir::new().unwrap();
  let store = new_store(dir.path());

  let testdir = TestDirectory::containing_roland();
  let testdata = TestData::fourty_chars();

  block_on(store.store_bytes(EntryType::Directory, testdir.bytes(), true)).expect("Error storing");

  block_on(store.store_bytes(EntryType::File, testdata.bytes(), false)).expect("Error storing");

  store
    .shrink(80, ShrinkBehavior::Fast)
    .expect("Error shrinking");

  assert_eq!(
    load_bytes(&store, EntryType::File, testdata.digest()),
    Ok(None),
    "File was present when it should've been garbage collected"
  );
  assert_eq!(
    load_bytes(&store, EntryType::Directory, testdir.digest()),
    Ok(Some(testdir.bytes())),
    "Directory was missing despite lease"
  );
}

#[test]
fn garbage_collect_remove_file_while_leased_file() {
  let dir = TempDir::new().unwrap();
  let store = new_store(dir.path());

  let testdir = TestDirectory::containing_roland();

  block_on(store.store_bytes(EntryType::Directory, testdir.bytes(), false)).expect("Error storing");
  let fourty_chars = TestData::fourty_chars();
  block_on(store.store_bytes(EntryType::File, fourty_chars.bytes(), true)).expect("Error storing");

  store
    .shrink(80, ShrinkBehavior::Fast)
    .expect("Error shrinking");

  assert_eq!(
    load_bytes(&store, EntryType::File, fourty_chars.digest()),
    Ok(Some(fourty_chars.bytes())),
    "File was missing despite lease"
  );
  assert_eq!(
    load_bytes(&store, EntryType::Directory, testdir.digest()),
    Ok(None),
    "Directory was present when it should've been garbage collected"
  );
}

#[test]
fn garbage_collect_fail_because_too_many_leases() {
  let dir = TempDir::new().unwrap();
  let store = new_store(dir.path());

  let testdir = TestDirectory::containing_roland();
  let fourty_chars = TestData::fourty_chars();

  block_on(store.store_bytes(EntryType::Directory, testdir.bytes(), true)).expect("Error storing");
  block_on(store.store_bytes(EntryType::File, fourty_chars.bytes(), true)).expect("Error storing");

  block_on(store.store_bytes(EntryType::File, TestData::roland().bytes(), false))
    .expect("Error storing");

  assert_eq!(store.shrink(80, ShrinkBehavior::Fast), Ok(160));

  assert_eq!(
    load_bytes(&store, EntryType::File, fourty_chars.digest()),
    Ok(Some(fourty_chars.bytes())),
    "Leased file should still be present"
  );
  assert_eq!(
    load_bytes(&store, EntryType::Directory, testdir.digest()),
    Ok(Some(testdir.bytes())),
    "Leased directory should still be present"
  );
  // Whether the unleased file is present is undefined.
}

#[test]
fn garbage_collect_and_compact() {
  let dir = TempDir::new().unwrap();
  let store = new_store(dir.path());

  let write_one_meg = |byte: u8| {
    let mut bytes = BytesMut::with_capacity(1024 * 1024);
    for _ in 0..1024 * 1024 {
      bytes.put(byte);
    }
    block_on(store.store_bytes(EntryType::File, bytes.freeze(), false)).expect("Error storing");
  };

  write_one_meg(b'0');

  write_one_meg(b'1');

  let size = get_directory_size(dir.path());
  assert!(
    size >= 2 * 1024 * 1024,
    "Expect size to be at least 2MB but was {}",
    size
  );

  store
    .shrink(1024 * 1024, ShrinkBehavior::Compact)
    .expect("Error shrinking");

  let size = get_directory_size(dir.path());
  assert!(
    size < 2 * 1024 * 1024,
    "Expect size to be less than 2MB but was {}",
    size
  );
}

#[test]
fn entry_type_for_file() {
  let testdata = TestData::roland();
  let testdir = TestDirectory::containing_roland();
  let dir = TempDir::new().unwrap();
  let store = new_store(dir.path());
  block_on(store.store_bytes(EntryType::Directory, testdir.bytes(), false)).expect("Error storing");
  prime_store_with_file_bytes(&store, testdata.bytes());
  assert_eq!(
    store.entry_type(&testdata.fingerprint()),
    Ok(Some(EntryType::File))
  )
}

#[test]
fn entry_type_for_directory() {
  let testdata = TestData::roland();
  let testdir = TestDirectory::containing_roland();
  let dir = TempDir::new().unwrap();
  let store = new_store(dir.path());
  block_on(store.store_bytes(EntryType::Directory, testdir.bytes(), false)).expect("Error storing");
  prime_store_with_file_bytes(&store, testdata.bytes());
  assert_eq!(
    store.entry_type(&testdir.fingerprint()),
    Ok(Some(EntryType::Directory))
  )
}

#[test]
fn entry_type_for_missing() {
  let testdata = TestData::roland();
  let testdir = TestDirectory::containing_roland();
  let dir = TempDir::new().unwrap();
  let store = new_store(dir.path());
  block_on(store.store_bytes(EntryType::Directory, testdir.bytes(), false)).expect("Error storing");
  prime_store_with_file_bytes(&store, testdata.bytes());
  assert_eq!(
    store.entry_type(&TestDirectory::recursive().fingerprint()),
    Ok(None)
  )
}

#[test]
pub fn empty_file_is_known() {
  let dir = TempDir::new().unwrap();
  let store = new_store(dir.path());
  let empty_file = TestData::empty();
  assert_eq!(
    block_on(store.load_bytes_with(EntryType::File, empty_file.digest(), |b| b)),
    Ok(Some(empty_file.bytes())),
  )
}

#[test]
pub fn empty_directory_is_known() {
  let dir = TempDir::new().unwrap();
  let store = new_store(dir.path());
  let empty_dir = TestDirectory::empty();
  assert_eq!(
    block_on(store.load_bytes_with(EntryType::Directory, empty_dir.digest(), |b| b)),
    Ok(Some(empty_dir.bytes())),
  )
}

#[test]
pub fn all_digests() {
  let dir = TempDir::new().unwrap();
  let store = new_store(dir.path());
  let digest = prime_store_with_file_bytes(&store, TestData::roland().bytes());
  assert_eq!(Ok(vec![digest]), store.all_digests(EntryType::File));
}

pub fn new_store<P: AsRef<Path>>(dir: P) -> ByteStore {
  ByteStore::new(task_executor::Executor::new(), dir, None).unwrap()
}

pub fn load_file_bytes(store: &ByteStore, digest: Digest) -> Result<Option<Bytes>, String> {
  load_bytes(&store, EntryType::File, digest)
}

pub fn load_directory_proto_bytes(
  store: &ByteStore,
  digest: Digest,
) -> Result<Option<Bytes>, String> {
  load_bytes(&store, EntryType::Directory, digest)
}

fn load_bytes(
  store: &ByteStore,
  entry_type: EntryType,
  digest: Digest,
) -> Result<Option<Bytes>, String> {
  block_on(store.load_bytes_with(entry_type, digest, |b| b))
}

fn prime_store_with_file_bytes(store: &ByteStore, bytes: Bytes) -> Digest {
  block_on(store.store_bytes(EntryType::File, bytes, false)).expect("Error storing file bytes")
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
