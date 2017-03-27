// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fs::create_dir;
use std::io::{Error, ErrorKind};
use std::path::Path;

use tempdir::TempDir;


// Like std::fs::create_dir_all, except handles concurrent calls among multiple
// threads or processes. Originally lifted from rustc.
fn safe_create_dir_all_ioerror(path: &Path) -> Result<(), Error> {
  match create_dir(path) {
    Ok(()) => return Ok(()),
    Err(ref e) if e.kind() == ErrorKind::AlreadyExists => return Ok(()),
    Err(ref e) if e.kind() == ErrorKind::NotFound => {}
    Err(e) => return Err(e),
  }
  match path.parent() {
    Some(p) => try!(safe_create_dir_all_ioerror(p)),
    None => return Ok(()),
  }
  match create_dir(path) {
    Ok(()) => Ok(()),
    Err(ref e) if e.kind() == ErrorKind::AlreadyExists => Ok(()),
    Err(e) => Err(e),
  }
}


pub fn safe_create_dir_all(path: &Path) -> Result<(), String> {
  safe_create_dir_all_ioerror(path).map_err(|e| format!("Failed to create dir {:?} due to {:?}", path, e))
}


pub fn safe_create_tmpdir_in(base_dir: &Path, prefix: &str) -> Result<TempDir, String> {
  safe_create_dir_all(&base_dir)?;
  Ok(
    TempDir::new_in(&base_dir, prefix)
      .map_err(|e| format!("Failed to create tempdir {:?} due to {:?}", base_dir, e))?
  )
}
