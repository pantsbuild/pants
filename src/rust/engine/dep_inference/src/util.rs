// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::path::{Component, Path, PathBuf};

/// Creates a [`PathBuf`], normalizing `.` and `..`.
///
/// Returns [`None`] when the normalization walks out of
/// the [`Path`]s base.
/// This is different to [`NormalizePath`](https://docs.rs/normalize-path/latest/normalize_path/trait.NormalizePath.html),
/// which returns the file name in this case.
pub fn normalize_path(path: &Path) -> Option<PathBuf> {
  let mut components = path.components().peekable();
  let mut ret = if let Some(c @ Component::Prefix(..)) = components.peek().cloned() {
    components.next();
    PathBuf::from(c.as_os_str())
  } else {
    PathBuf::new()
  };

  for component in components {
    match component {
      Component::Prefix(..) => unreachable!(),
      Component::RootDir => {
        ret.push(component.as_os_str());
      }
      Component::CurDir => {}
      Component::ParentDir => {
        if !ret.pop() {
          return None;
        }
      }
      Component::Normal(c) => {
        ret.push(c);
      }
    }
  }
  Some(ret)
}
