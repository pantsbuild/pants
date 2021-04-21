// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

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
