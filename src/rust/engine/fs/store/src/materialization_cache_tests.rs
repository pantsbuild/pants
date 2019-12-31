use crate::local::ByteStore;
use crate::materialization_cache::{
  CachedFileMaterializationState, CanonicalFileMaterializationRequest, FileMaterializationInput,
  LocalFileMaterializationCache, CachedFileToMaterialize,
};
use crate::tests::{block_on, is_executable};
use crate::{FileMaterializationBehavior, Store};

use concrete_time::Duration;
use hashing::EMPTY_DIGEST;
use tempfile::TempDir;
use testutil::data::TestData;
use workunit_store::WorkUnitStore;

use std::convert::From;
use std::fs;
use std::io::{self, Write};
use std::path::PathBuf;

#[derive(Debug)]
struct Error(String);

impl From<io::Error> for Error {
  fn from(e: io::Error) -> Error {
    Error(format!("{}", e))
  }
}

impl From<String> for Error {
  fn from(e: String) -> Error {
    Error(e)
  }
}

#[test]
fn file_materialization_cache() -> Result<(), Error> {
  // Create a file materialization cache which will start creating symlinks after 2 materialization
  // attempts.
  let cache_dir = TempDir::new()?;
  let cache = LocalFileMaterializationCache::new(cache_dir.path(), 2, Duration::default())?;

  let store_dir = TempDir::new()?;
  let store = Store {
    local: ByteStore::new(
      task_executor::Executor::new(),
      store_dir.path(),
      Some(cache),
    )?,
    remote: None,
  };

  let materialize_dir = TempDir::new()?;
  let file = materialize_dir.path().join("file");
  let testdata = TestData::roland();
  block_on(store.store_file_bytes(testdata.bytes(), false))?;

  let materialize_file = |file: &PathBuf, testdata: &TestData, is_executable: bool| {
    store.materialize_file(
      file.clone(),
      testdata.digest(),
      is_executable,
      FileMaterializationBehavior::AllowSymlinkOptimization,
      WorkUnitStore::new(),
    )
  };

  block_on(materialize_file(&file, &testdata, false))?;
  assert!(fs::symlink_metadata(&file)?.is_file());

  // Check that attempting to create a symlink at an existing file location produces an Err.
  assert!(block_on(materialize_file(&file, &testdata, false)).is_err());
  fs::remove_file(&file)?;

  // Create the file a second time, which should produce a symlink now.
  block_on(materialize_file(&file, &testdata, false))?;
  assert!(fs::symlink_metadata(&file)?.file_type().is_symlink());
  assert!(!is_executable(&file));

  // Check that materializing with is_executable=true modifies the cache key.
  block_on(materialize_file(&file, &testdata, true))?;
  assert!(fs::symlink_metadata(&file)?.is_file());
  fs::remove_file(&file)?;
  block_on(materialize_file(&file, &testdata, true))?;
  assert!(fs::symlink_metadata(&file)?.file_type().is_symlink());
  // Check that the underlying file is correctly marked as executable!
  assert!(is_executable(&file));

  Ok(())
}

#[test]
fn cache_serde_on_new_and_drop() -> Result<(), Error> {
  let tmp_dir = TempDir::new()?;
  let cache_dir = tmp_dir.path();
  let empty_input = FileMaterializationInput {
    digest: EMPTY_DIGEST,
    is_executable: false,
  };
  let cache_file_path = cache_dir.join("idk.txt");
  let cache_info_file_path = cache_dir.join("cache-info.json");

  // Create new file materialization cache.
  assert!(!cache_info_file_path.exists());
  {
    // Large enough to be longer than the duration of this test running.
    let duration = Duration::new(100, 0);
    let mut cache = LocalFileMaterializationCache::new(cache_dir, 2, duration)?;
    // First use should signal no caching needs to be done.
    assert_eq!(
      cache.determine_materialization_state_for_file(empty_input),
      CachedFileMaterializationState::HasNoCanonicalMaterialization
    );
    let to_materialize = match cache.determine_materialization_state_for_file(empty_input) {
      CachedFileMaterializationState::RequiresCanonicalMaterialization(
        CanonicalFileMaterializationRequest {
          input, materialize_into_dir,
        }
      ) => {
        assert_eq!(input, empty_input);
        assert_eq!(materialize_into_dir, cache_dir);
        fs::File::create(&cache_file_path)?.write_all(b"")?;
        let to_materialize = CachedFileToMaterialize {
          input,
          canonical_materialized_location: cache_file_path.clone(),
        };
        cache.register_newly_materialized_file(to_materialize.clone())?;
        to_materialize
      },
      _ => unreachable!(),
    };
    assert_eq!(cache.determine_materialization_state_for_file(empty_input),
               CachedFileMaterializationState::AlreadyCanonicallyMaterialized(to_materialize));
  }
  // After `cache` is `drop()`ed, the info file should be populated.
  assert!(cache_info_file_path.exists());

  // Create another `cache`, with a much shorter (0) ttl.
  {
    let duration = Duration::default();
    let mut cache = LocalFileMaterializationCache::new(cache_dir, 2, duration)?;

    // The previous entry should already exist in a materialized state.
    match cache.determine_materialization_state_for_file(empty_input) {
      CachedFileMaterializationState::AlreadyCanonicallyMaterialized(CachedFileToMaterialize {
        input,
        canonical_materialized_location,
      }) => {
        assert_eq!(input, empty_input);
        assert_eq!(canonical_materialized_location, cache_file_path.clone());
      },
      _ => unreachable!(),
    }

    assert!(cache_file_path.exists());
  }
  // After the `drop()` from a cache with a 0 ttl, the single entry should be wiped.
  assert!(!cache_file_path.exists());
  // The cache info file should still exist.
  assert!(cache_info_file_path.exists());

  Ok(())
}
