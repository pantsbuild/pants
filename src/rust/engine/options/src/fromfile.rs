// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use super::{BuildRoot, DictEdit, DictEditAction, ListEdit, ListEditAction};

use crate::parse::{mk_parse_err, parse_dict, ParseError, Parseable};
use log::warn;
use serde::de::Deserialize;
use std::path::{Path, PathBuf};
use std::{fs, io};

// If the corresponding unexpanded value points to a @fromfile, then the
// first component is the path to that file, and the second is the value from the file,
// or None if the file doesn't exist and the @?fromfile syntax was used.
//
// Otherwise, the first component is None and the second is the original value.
type ExpandedValue = (Option<PathBuf>, Option<String>);

#[derive(Debug)]
enum FromfileType {
    Json,
    Yaml,
    Unknown,
}

impl FromfileType {
    fn detect(path: &Path) -> FromfileType {
        if let Some(ext) = path.extension() {
            if ext == "json" {
                return FromfileType::Json;
            } else if ext == "yml" || ext == "yaml" {
                return FromfileType::Yaml;
            };
        }
        FromfileType::Unknown
    }
}

fn try_deserialize<'a, DE: Deserialize<'a>>(
    value: &'a str,
    path_opt: Option<PathBuf>,
) -> Result<Option<DE>, ParseError> {
    if let Some(path) = path_opt {
        match FromfileType::detect(&path) {
            FromfileType::Json => serde_json::from_str(value).map_err(|e| mk_parse_err(e, &path)),
            FromfileType::Yaml => serde_yaml::from_str(value).map_err(|e| mk_parse_err(e, &path)),
            _ => Ok(None),
        }
    } else {
        Ok(None)
    }
}

#[derive(Clone, Debug)]
pub struct FromfileExpander {
    build_root: BuildRoot,
}

impl FromfileExpander {
    // Creates a FromfileExpander that treats relpaths as relative to the build root.
    pub fn relative_to(build_root: BuildRoot) -> Self {
        Self {
            build_root: build_root,
        }
    }

    // Creates a FromfileExpander that treats relpaths as relative to the CWD.
    // Useful in tests.
    #[cfg(test)]
    pub(crate) fn relative_to_cwd() -> Self {
        Self {
            build_root: BuildRoot::for_path(PathBuf::from("")),
        }
    }

    fn maybe_expand(&self, value: String) -> Result<ExpandedValue, ParseError> {
        if let Some(suffix) = value.strip_prefix('@') {
            if suffix.starts_with('@') {
                // @@ escapes the initial @.
                Ok((None, Some(suffix.to_owned())))
            } else {
                match suffix.strip_prefix('?') {
                    Some(subsuffix) => {
                        // @? means the path is allowed to not exist.
                        let path = self.build_root.join(subsuffix);
                        match fs::read_to_string(&path) {
                            Ok(content) => Ok((Some(path), Some(content))),
                            Err(err) if err.kind() == io::ErrorKind::NotFound => {
                                warn!("Optional file config '{}' does not exist.", path.display());
                                Ok((Some(path), None))
                            }
                            Err(err) => Err(mk_parse_err(err, &path)),
                        }
                    }
                    _ => {
                        let path = self.build_root.join(suffix);
                        let content =
                            fs::read_to_string(&path).map_err(|e| mk_parse_err(e, &path))?;
                        Ok((Some(path), Some(content)))
                    }
                }
            }
        } else {
            Ok((None, Some(value)))
        }
    }

    pub(crate) fn expand(&self, value: String) -> Result<Option<String>, ParseError> {
        let (_, expanded_value) = self.maybe_expand(value)?;
        Ok(expanded_value)
    }

    pub(crate) fn expand_to_list<T: Parseable>(
        &self,
        value: String,
    ) -> Result<Option<Vec<ListEdit<T>>>, ParseError> {
        let (path_opt, value_opt) = self.maybe_expand(value)?;
        if let Some(value) = value_opt {
            if let Some(items) = try_deserialize(&value, path_opt)? {
                Ok(Some(vec![ListEdit {
                    action: ListEditAction::Replace,
                    items,
                }]))
            } else {
                T::parse_list(&value).map(Some)
            }
        } else {
            Ok(None)
        }
    }

    pub(crate) fn expand_to_dict(
        &self,
        value: String,
    ) -> Result<Option<Vec<DictEdit>>, ParseError> {
        let (path_opt, value_opt) = self.maybe_expand(value)?;
        if let Some(value) = value_opt {
            if let Some(items) = try_deserialize(&value, path_opt)? {
                Ok(Some(vec![DictEdit {
                    action: DictEditAction::Replace,
                    items,
                }]))
            } else {
                parse_dict(&value).map(|x| Some(vec![x]))
            }
        } else {
            Ok(None)
        }
    }
}

#[cfg(test)]
pub(crate) mod test_util {
    use std::fs::File;
    use std::io::Write;
    use std::path::PathBuf;
    use tempfile::{tempdir, TempDir};

    pub(crate) fn write_fromfile(filename: &str, content: &str) -> (TempDir, PathBuf) {
        let tmpdir = tempdir().unwrap();
        let fromfile_path = tmpdir.path().join(filename);
        let mut fromfile = File::create(&fromfile_path).unwrap();
        fromfile.write_all(content.as_bytes()).unwrap();
        fromfile.flush().unwrap();
        (tmpdir, fromfile_path)
    }
}
