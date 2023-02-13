// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use deepsize::DeepSizeOf;
use serde::Serialize;

use fs::{default_cache_path, safe_create_dir_all, RelativePath};
use store::WorkdirSymlink;

#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq, Hash, PartialOrd, Ord, Serialize)]
pub struct CacheName(String);

impl CacheName {
  pub fn new(name: String) -> Result<CacheName, String> {
    if name
      .chars()
      .all(|c| (c.is_ascii_alphanumeric() && c.is_ascii_lowercase()) || c == '_')
    {
      Ok(CacheName(name))
    } else {
      Err(format!(
        "Cache names may only contain lowercase alphanumeric characters or underscores: got {name:?}"
      ))
    }
  }

  pub fn name(&self) -> &str {
    &self.0
  }
}

#[derive(Clone)]
pub struct NamedCaches {
  ///
  /// The absolute path to the base of the directory storing named caches. Pants "owns" this
  /// directory, and may clear or otherwise prune it at any time.
  ///
  local_base: PathBuf,
}

impl NamedCaches {
  pub fn new(local_base: PathBuf) -> Result<NamedCaches, String> {
    safe_create_dir_all(&local_base)?;
    Ok(Self { local_base })
  }

  pub fn base_dir(&self) -> &Path {
    &self.local_base
  }

  // This default suffix is also hard-coded into the Python options code in global_options.py
  pub fn default_path() -> PathBuf {
    default_cache_path().join("named_caches")
  }

  ///
  /// Returns symlinks to create for the given set of NamedCaches.
  ///
  pub fn local_paths<'a>(
    &'a self,
    caches: &'a BTreeMap<CacheName, RelativePath>,
  ) -> Result<Vec<WorkdirSymlink>, String> {
    let symlinks = caches
      .iter()
      .map(move |(cache_name, workdir_rel_path)| WorkdirSymlink {
        src: workdir_rel_path.clone(),
        dst: self.local_base.join(&cache_name.0),
      })
      .collect::<Vec<_>>();

    for symlink in &symlinks {
      safe_create_dir_all(&symlink.dst)?;
    }

    Ok(symlinks)
  }

  ///
  /// An iterator over platform properties that should be added for the given named caches, and the
  /// given named cache namespace value.
  ///
  /// See <https://docs.google.com/document/d/1n_MVVGjrkTKTPKHqRPlyfFzQyx2QioclMG_Q3DMUgYk/edit#>.
  ///
  pub fn platform_properties<'a>(
    caches: &'a BTreeMap<CacheName, RelativePath>,
    namespace: &'a Option<String>,
  ) -> impl Iterator<Item = (String, String)> + 'a {
    namespace
      .iter()
      .map(|ns| ("x_append_only_cache_namespace".to_owned(), ns.to_owned()))
      .chain(caches.iter().map(move |(cache_name, cache_dest)| {
        (
          format!("x_append_only_cache:{}", cache_name.0),
          cache_dest.display().to_string(),
        )
      }))
  }
}
