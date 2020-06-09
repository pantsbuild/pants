use std::collections::BTreeMap;
use std::path::PathBuf;

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
pub struct CacheDest(PathBuf);

impl CacheDest {
  pub fn new(dest: String) -> Result<CacheDest, String> {
    let dest = PathBuf::from(dest);
    if dest.is_relative() && dest.components().next().is_some() {
      Ok(CacheDest(dest))
    } else {
      Err(format!(
        "Cache paths must be relative and non-empty: got: {}",
        dest.display()
      ))
    }
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
        dst: cache_dest.0.clone(),
      })
  }
}
