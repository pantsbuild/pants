use std::collections::BTreeMap;
use std::path::PathBuf;

use crate::RelativePath;

#[derive(Clone, Debug, Eq, PartialEq, Hash, PartialOrd, Ord)]
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
        "Cache names may only contain lowercase alphanumeric characters or underscores: got {:?}",
        name
      ))
    }
  }
}

#[derive(Clone, Debug, Eq, PartialEq, Hash)]
pub struct CacheDest(String);

impl CacheDest {
  pub fn new(dest: String) -> Result<CacheDest, String> {
    // We validate as RelativePath, but store as a String to avoid needing to assert later that
    // path is valid unicode.
    let _ = RelativePath::new(&dest)?;
    Ok(CacheDest(dest))
  }
}

#[derive(Debug)]
pub struct NamedCacheSymlink {
  pub src: PathBuf,
  pub dst: PathBuf,
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
  pub fn new(local_base: PathBuf) -> NamedCaches {
    NamedCaches { local_base }
  }

  ///
  /// Returns symlinks to create for the given set of NamedCaches.
  ///
  pub fn local_paths<'a>(
    &'a self,
    caches: &'a BTreeMap<CacheName, CacheDest>,
  ) -> impl Iterator<Item = NamedCacheSymlink> + 'a {
    caches
      .iter()
      .map(move |(cache_name, cache_dest)| NamedCacheSymlink {
        src: self.local_base.join(&cache_name.0),
        dst: PathBuf::from(&cache_dest.0),
      })
  }

  ///
  /// An iterator over platform properties that should be added for the given named caches, and the
  /// given named cache namespace value.
  ///
  /// See https://docs.google.com/document/d/1n_MVVGjrkTKTPKHqRPlyfFzQyx2QioclMG_Q3DMUgYk/edit#.
  ///
  pub fn platform_properties<'a>(
    caches: &'a BTreeMap<CacheName, CacheDest>,
    namespace: &'a Option<String>,
  ) -> impl Iterator<Item = (String, String)> + 'a {
    namespace
      .iter()
      .map(|ns| ("x_append_only_cache_namespace".to_owned(), ns.to_owned()))
      .chain(caches.iter().map(move |(cache_name, cache_dest)| {
        (
          format!("x_append_only_cache:{}", cache_name.0),
          cache_dest.0.clone(),
        )
      }))
  }
}
