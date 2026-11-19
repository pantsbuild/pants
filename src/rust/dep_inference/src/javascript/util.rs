// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::borrow::Cow;
use std::path::{Component, Path, PathBuf};

/// Converts the `/` separators of a JavaScript import specifier to the platform's separator.
///
/// Specifiers always use `/`, but the file paths we return are native paths. Only allocates
/// when there is something to convert, so never on Unix.
pub fn to_native_separators(path: &str) -> Cow<'_, str> {
    if cfg!(windows) && path.contains('/') {
        Cow::Owned(path.replace('/', std::path::MAIN_SEPARATOR_STR))
    } else {
        Cow::Borrowed(path)
    }
}

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
