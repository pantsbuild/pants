use concrete_time::Duration;
use hashing::Digest;

use serde_derive::{Deserialize, Serialize};
use serde_json;

use std::collections::{HashMap, HashSet};
use std::default::Default;
use std::fs;
use std::io::Write;
use std::ops::Drop;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

// NB: This is always going to refer to a *file*, never a *directory*!
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize, Deserialize)]
pub struct FileMaterializationInput {
  pub digest: Digest,
  pub is_executable: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CachedFileToMaterialize {
  pub input: FileMaterializationInput,
  pub canonical_materialized_location: PathBuf,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalFileMaterializationRequest {
  pub input: FileMaterializationInput,
  // NB: This directory is the *base* directory to materialize files into -- this is *not* a path
  // pointing to the canonical materialization location! The recipient of this struct is expected to
  // create the canonical materialization location and provide a `CachedFileToMaterialize` to
  // `LocalFileMaterializationCache::register_newly_materialized_file()!
  pub materialize_into_dir: PathBuf,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct MaterializationCacheEntry {
  pub last_accessed: SystemTime,
  pub num_occurrences: u64,
  pub canonical_location: Option<PathBuf>,
}

impl Default for MaterializationCacheEntry {
  fn default() -> Self {
    MaterializationCacheEntry {
      last_accessed: SystemTime::now(),
      num_occurrences: 0,
      canonical_location: None,
    }
  }
}

///
/// We attempt to create a "secretly" mutable cache of files we have materialized on disk. We
/// want to use this to create symlinks when materializing files which are materialized to disk
/// *extremely* often.
///
#[derive(Debug)]
pub struct LocalFileMaterializationCache {
  // TODO: Determine whether u64 is sufficiently large to avoid wrapping back over to 0! This should
  // be an easy question with an easy answer!
  all_materializations: HashMap<FileMaterializationInput, MaterializationCacheEntry>,
  // If a file is materialized this many times, create a "canonical file materialization", and
  // henceforth create a symlink to that file when materializing files locally!
  canonical_file_materialization_threshold: u64,
  ttl: Duration,
  // The directory where we store what we call "canonical file materializations" (note that
  // "canonical" is used in many different ways in this codebase!). "Canonical file
  // materializations" here are files we materialize within this
  // directory.
  materialize_into_dir: PathBuf,
  // Path to the file which contains persisted cache information that is re-read in
  // `LocalFileMaterializationCache::new()`. A json blob is written to this file path on Drop.
  cache_info_file_path: PathBuf,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CachedFileMaterializationState {
  AlreadyCanonicallyMaterialized(CachedFileToMaterialize),
  RequiresCanonicalMaterialization(CanonicalFileMaterializationRequest),
  HasNoCanonicalMaterialization,
}

impl LocalFileMaterializationCache {
  pub fn new<P: AsRef<Path>>(
    materialize_into_dir: P,
    canonical_file_materialization_threshold: u64,
    ttl: Duration,
  ) -> Result<Self, String> {
    let materialize_into_dir = materialize_into_dir.as_ref().to_path_buf();
    if !materialize_into_dir.is_dir() {
      return Err(format!(
        "the specified directory for the file materialization cache at {:?} is not a directory!",
        &materialize_into_dir
      ));
    }

    let cache_info_file_path = materialize_into_dir.join("cache-info.json");
    let persisted_state = match fs::read_to_string(&cache_info_file_path) {
      Err(_) => PersistedFileMaterializationState::default(),
      Ok(file_contents) => serde_json::from_str(&file_contents).map_err(|e| format!("{}", e))?,
    };

    let PersistedFileMaterializationState {
      all_materializations,
    } = persisted_state;

    Ok(LocalFileMaterializationCache {
      all_materializations: all_materializations.into_iter().collect(),
      canonical_file_materialization_threshold,
      materialize_into_dir,
      cache_info_file_path,
      ttl,
    })
  }

  ///
  /// This method will register the `digest` as an "attempted materialization", and if this method
  /// is called with the same `digest` enough times, it will eventually return a
  /// RequiresCanonicalMaterialization!
  ///
  pub fn determine_materialization_state_for_file(
    &mut self,
    input: FileMaterializationInput,
  ) -> CachedFileMaterializationState {
    let (num_occurrences, maybe_cached_materialization) = {
      let entry = self.all_materializations.entry(input).or_default();
      // Update the last access time to now.
      (*entry).last_accessed = SystemTime::now();
      // Increment the number of occurrences for the given `input`.
      (*entry).num_occurrences += 1;
      ((*entry).num_occurrences, &(*entry).canonical_location)
    };

    if let &Some(ref cached_materialization) = maybe_cached_materialization {
      CachedFileMaterializationState::AlreadyCanonicallyMaterialized(CachedFileToMaterialize {
        input,
        canonical_materialized_location: cached_materialization.clone(),
      })
    } else if num_occurrences >= self.canonical_file_materialization_threshold {
      CachedFileMaterializationState::RequiresCanonicalMaterialization(
        CanonicalFileMaterializationRequest {
          input,
          materialize_into_dir: self.materialize_into_dir.clone(),
        },
      )
    } else {
      CachedFileMaterializationState::HasNoCanonicalMaterialization
    }
  }

  ///
  /// If the caller previously received a
  /// `CachedFileMaterializationState::RequiresCanonicalMaterialization`, they should call this
  /// method so that subsequent invocations of `self.determine_materialization_state_for_file()`
  /// will return a `CachedFileMaterializationState::AlreadyCanonicallyMaterialized`!
  ///
  pub fn register_newly_materialized_file(
    &mut self,
    newly_materialized_file: CachedFileToMaterialize,
  ) -> Result<(), String> {
    let CachedFileToMaterialize {
      input,
      canonical_materialized_location,
    } = newly_materialized_file;

    let mut entry = self.all_materializations.get_mut(&input)
      .ok_or_else(|| format!("input {:?} attempted to be registered as a canonical file materialization at {:?}, but the canonical file materialization cache has never seen this input!",
                             &input, &canonical_materialized_location,
      ))?;

    if entry.canonical_location.is_some() {
      Ok(())
    } else if entry.num_occurrences < self.canonical_file_materialization_threshold {
      Err(format!("input {:?} was registered as a canonical file materialization at {:?}, but was only seen {:?} times, less than the threshold of {:?}!",
                  &input, &canonical_materialized_location, &entry.num_occurrences, self.canonical_file_materialization_threshold))
    } else {
      // We have encountered a valid, newly-registered canonical file materialization!
      entry.canonical_location = Some(canonical_materialized_location);
      Ok(())
    }
  }

  fn write_persisted_state(&self) -> Result<(), String> {
    let persisted_state = PersistedFileMaterializationState::extract(&self);
    let mut file = fs::File::create(&self.cache_info_file_path).map_err(|e| {
      format!(
        "{:?} could not be created: {}",
        &self.cache_info_file_path, e
      )
    })?;
    let json_payload = serde_json::to_string_pretty(&persisted_state).map_err(|e| {
      format!(
        "persisted state {:?} could not be converted to json: {:?}",
        &persisted_state, e
      )
    })?;
    file.write_all(json_payload.as_bytes()).map_err(|e| {
      format!(
        "error writing json payload {:?} to file {:?}: {}",
        json_payload, file, e
      )
    })?;
    Ok(())
  }

  fn get_old_entries(
    &mut self,
  ) -> Vec<(&FileMaterializationInput, &mut MaterializationCacheEntry)> {
    let now = std::time::SystemTime::now();
    let ttl = self.ttl;
    self
      .all_materializations
      .iter_mut()
      .filter(
        move |(
          _,
          MaterializationCacheEntry {
            last_accessed,
            canonical_location,
            ..
          },
        )| {
          let diff: Duration = now
            .duration_since(*last_accessed)
            .map(|d| d.into())
            .unwrap_or_default();
          diff > ttl && canonical_location.is_some()
        },
      )
      .collect()
  }

  fn cleanup_old_entries(&mut self) -> Result<(), String> {
    // Remove files belonging to any cache entries older than the ttl.
    for (ref input, ref mut entry) in self.get_old_entries().into_iter() {
      let location = entry.canonical_location.clone().unwrap();
      fs::remove_file(&location).map_err(|e| {
        format!(
          "failed to clean up old entry {:?} for input {:?}: {}",
          &input, &entry, e
        )
      })?;
      entry.canonical_location = None;
    }

    // Cleanup any files in the cache directory that aren't recognized by the current set of
    // entries.
    let mut unrecognized_files: HashSet<_> = fs::read_dir(&self.materialize_into_dir)
      .map_err(|e| {
        format!(
          "reading file materialization cache dir {:?} failed: {}",
          self.materialize_into_dir, e
        )
      })?
      .map(|dir_entry| dir_entry.map(|d| d.path()))
      .collect::<Result<HashSet<_>, _>>()
      .map_err(|e| {
        format!(
          "reading file materialization cache dir {:?} failed: {}",
          self.materialize_into_dir, e
        )
      })?;
    // Avoid deleting the cache info file.
    unrecognized_files.remove(&self.cache_info_file_path);
    // Unmark all files that did survive the ttl-based cache purge.
    for canonical_location in self.all_materializations.iter().flat_map(
      |(
        _,
        MaterializationCacheEntry {
          ref canonical_location,
          ..
        },
      )| canonical_location,
    ) {
      assert!(unrecognized_files.remove(canonical_location));
    }
    for file in unrecognized_files.into_iter() {
      fs::remove_file(&file)
        .map_err(|e| format!("failed to remove unrecognized file {:?}: {}", file, e))?;
    }

    Ok(())
  }
}

#[derive(Serialize, Deserialize, Default, Debug)]
struct PersistedFileMaterializationState {
  pub all_materializations: Vec<(FileMaterializationInput, MaterializationCacheEntry)>,
}

impl PersistedFileMaterializationState {
  fn extract(cache: &LocalFileMaterializationCache) -> Self {
    let &LocalFileMaterializationCache {
      ref all_materializations,
      ..
    } = cache;
    PersistedFileMaterializationState {
      all_materializations: all_materializations
        .iter()
        .map(|(input, entry)| (*input, entry.clone()))
        .collect(),
    }
  }
}

impl Drop for LocalFileMaterializationCache {
  fn drop(&mut self) {
    self
      .cleanup_old_entries()
      .unwrap_or_else(|e| panic!("error cleaning up old entries: {}", e));
    self
      .write_persisted_state()
      .unwrap_or_else(|e| panic!("error writing persisted materialization cache info: {}", e));
  }
}
