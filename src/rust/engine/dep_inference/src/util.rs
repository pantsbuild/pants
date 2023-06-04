use std::path::{Component, Path, PathBuf};

/// Creates a [`std::path::PathBuf`], normalizing `.` and `..`.
/// Returns `None` when the normalized path is a parent directory
/// of `path`s base.
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
