// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::env;
use std::ops::Deref;
use std::path::PathBuf;

use log::debug;

#[derive(Debug)]
pub struct BuildRoot(PathBuf);

impl BuildRoot {
  const SENTINEL_FILES: &'static [&'static str] = &["pants", "BUILDROOT", "BUILD_ROOT"];

  pub fn find() -> Result<BuildRoot, String> {
    let cwd = env::current_dir().map_err(|e| format!("Failed to determine $CWD: {}", e))?;
    let mut build_root = cwd.clone();
    loop {
      for sentinel in Self::SENTINEL_FILES {
        let sentinel_path = build_root.join(sentinel);
        if !sentinel_path.exists() {
          continue;
        }
        let sentinel_path_metadata = sentinel_path.metadata().map_err(|e| {
          format!(
            "\
            Failed to read metadata for {path} to determine if is a build root sentinel file: {err}\
            ",
            path = sentinel_path.display(),
            err = e
          )
        })?;
        if sentinel_path_metadata.is_file() {
          let root = BuildRoot(build_root);
          debug!("Found {:?} starting search from {}.", root, cwd.display());
          return Ok(root);
        }
      }

      build_root = build_root
        .parent()
        .ok_or(format!(
          "\
          No build root detected for the current directory of {cwd}. Pants detects the build root \
          by looking for at least one file from {sentinel_files} in the cwd and its ancestors. If \
          you have none of these files, you can create an empty file in your build root.\
          ",
          cwd = cwd.display(),
          sentinel_files = Self::SENTINEL_FILES.join(", ")
        ))?
        .into();
    }
  }
}

impl Deref for BuildRoot {
  type Target = PathBuf;

  fn deref(&self) -> &PathBuf {
    &self.0
  }
}

#[cfg(test)]
mod test {
  use std::ops::Deref;
  use std::path::{Path, PathBuf};
  use std::{env, fs};

  use lazy_static::lazy_static;
  use parking_lot::Mutex;
  use tempdir::TempDir;

  use crate::build_root::BuildRoot;

  struct CurrentDir {
    prior_cwd: Option<PathBuf>,
    cwd: PathBuf,
  }

  impl CurrentDir {
    fn cwd() -> CurrentDir {
      CurrentDir {
        prior_cwd: None,
        cwd: env::current_dir().unwrap(),
      }
    }

    fn cd<P: AsRef<Path>>(&self, path: P) -> CurrentDir {
      let cwd = path.as_ref();
      fs::create_dir_all(cwd).unwrap();
      env::set_current_dir(cwd).unwrap();
      CurrentDir {
        prior_cwd: Some(self.cwd.clone()),
        cwd: cwd.into(),
      }
    }

    fn path(&self) -> &PathBuf {
      &self.cwd
    }
  }

  impl Drop for CurrentDir {
    fn drop(&mut self) {
      if let Some(prior_cwd) = self.prior_cwd.take() {
        env::set_current_dir(prior_cwd).unwrap();
      }
    }
  }

  impl Deref for CurrentDir {
    type Target = PathBuf;

    fn deref(&self) -> &Self::Target {
      &self.cwd
    }
  }

  lazy_static! {
      // CWD is global to the process and Rust tests are multi-threaded by default; so we
      // serialize tests here that need to mutate CWD.
      static ref CWD: Mutex<CurrentDir> = Mutex::new(CurrentDir::cwd());
  }

  #[test]
  fn test_find_cwd() {
    let buildroot = TempDir::new("buildroot").unwrap();
    let cwd_lock = CWD.lock();
    let cwd = cwd_lock.cd(buildroot.path());

    let mut sentinel: Option<PathBuf> = None;

    let mut assert_sentinel = |name| {
      if let Some(prior_sentinel) = sentinel.take() {
        fs::remove_file(prior_sentinel).unwrap();
      }
      assert_eq!(buildroot.path(), env::current_dir().unwrap());
      assert!(BuildRoot::find().is_err());

      let file = cwd.join(name);
      fs::write(&file, &[]).unwrap();
      sentinel = Some(file);
      assert_eq!(buildroot.path(), env::current_dir().unwrap());
      assert_eq!(buildroot.path(), BuildRoot::find().unwrap().as_path());
    };

    assert_sentinel("BUILDROOT");
    assert_sentinel("BUILD_ROOT");
    assert_sentinel("pants");
  }

  #[test]
  fn test_find_subdir() {
    let buildroot = TempDir::new("buildroot").unwrap();
    let cwd_lock = CWD.lock();
    let subdir = cwd_lock.cd(buildroot.path().join("foo").join("bar"));

    assert_eq!(subdir.path(), &env::current_dir().unwrap());
    assert!(BuildRoot::find().is_err());

    let sentinel = &buildroot.path().join("pants");
    fs::write(&sentinel, &[]).unwrap();
    assert_eq!(subdir.path(), &env::current_dir().unwrap());
    assert_eq!(buildroot.path(), BuildRoot::find().unwrap().as_path());
  }
}
