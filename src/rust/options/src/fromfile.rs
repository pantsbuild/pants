// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use super::{BuildRoot, DictEdit, DictEditAction, ListEdit, ListEditAction};

use crate::parse::{ParseError, mk_parse_err, parse_dict};
use crate::{FromVal, Val};
use log::warn;
use serde::de::DeserializeOwned;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::{fs, io};

#[derive(Debug)]
enum FromfileType {
    Json,
    Yaml,
    Toml,
    Unknown,
}

impl FromfileType {
    fn detect(path: &Path) -> FromfileType {
        if let Some(ext) = path.extension() {
            if ext == "json" {
                return FromfileType::Json;
            } else if ext == "yml" || ext == "yaml" {
                return FromfileType::Yaml;
            } else if ext == "toml" {
                return FromfileType::Toml;
            };
        }
        FromfileType::Unknown
    }
}

struct ExpansionRequest {
    // The path to the file to expand from.
    path: PathBuf,

    // If Some(...), refers to a nested value in JSON/YAML/TOML dict parsed from the file.
    // E.g., ['bar', 'foo'] refers to the value at dict['foo']['bar'] (the Vec is reversed so that
    // we can pop as we descend). An empty Vec refers to the entire object.
    // If None, we don't attempt to parse the file, but instead return its content as a string.
    trail: Option<Vec<String>>,

    // If true, the file is allowed to not exist, and the expansion returns None.
    // If false, the file not existing is an error.
    optional: bool,
}

impl ExpansionRequest {
    // Possibly convert an option value string into an ExpansionRequest.
    //
    // If the value starts with `@` (but not `@@`) then treat it as an ExpansionRequest.
    // If that reference begins with `?` then the file is optional.
    // The reference can be either `path` or `path:trail`.
    //
    // Returns the created request, if any, and the value string to use downstream (this will
    // be the input string in all cases except a string that starts with `@@`, in which case
    // the leading `@` is stripped).
    fn from_value(value: String) -> (Option<Self>, String) {
        if let Some(suffix) = value.strip_prefix('@') {
            if suffix.starts_with('@') {
                // @@ escapes the initial @.
                (None, suffix.to_string())
            } else {
                let (path, trail) = match suffix.rsplit_once(":") {
                    Some((p, t)) => (p, Some(t)),
                    None => (suffix, None),
                };
                let (path, optional) = match path.strip_prefix('?') {
                    Some(subsuffix) => (subsuffix, true),
                    None => (path, false),
                };
                (
                    Some(Self {
                        path: PathBuf::from(path),
                        trail: trail.map(|s| {
                            s.split(".")
                                .map(str::to_string)
                                .collect::<Vec<_>>()
                                .into_iter()
                                .rev()
                                .collect()
                        }),
                        optional,
                    }),
                    value,
                )
            }
        } else {
            (None, value)
        }
    }
}

fn try_deserialize<DE: DeserializeOwned>(
    value: &str,
    path_opt: Option<&Path>,
) -> Result<Option<DE>, ParseError> {
    if let Some(path) = path_opt {
        match FromfileType::detect(path) {
            FromfileType::Json => serde_json::from_str(value).map_err(|e| mk_parse_err(e, path)),
            FromfileType::Yaml => serde_yaml::from_str(value).map_err(|e| mk_parse_err(e, path)),
            FromfileType::Toml => toml::from_str(value).map_err(|e| mk_parse_err(e, path)),
            _ => Ok(None),
        }
    } else {
        Ok(None)
    }
}

pub(crate) fn follow_the_trail(val: Val, mut trail: Vec<String>) -> Result<Val, String> {
    if let Some(key) = trail.pop() {
        if let Val::Dict(mut dict) = val {
            let val = dict
                .remove(&key)
                .ok_or_else(|| format!("No value for `{key}` in object"))?;
            follow_the_trail(val, trail)
        } else {
            Err("Value is not a dict".to_string())
        }
    } else {
        Ok(val)
    }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
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

    // Returns Ok(Some(content)) if the file exists.
    // Returns Ok(None) if the request is optional and the file doesn't exist.
    // Returns an Err(ParseError) otherwise.
    fn read_content_from_file(
        &self,
        expansion_request: &ExpansionRequest,
    ) -> Result<Option<String>, ParseError> {
        let path = self.build_root.join(&expansion_request.path);
        match fs::read_to_string(&path) {
            Ok(content) => Ok(Some(content)),
            Err(err) if expansion_request.optional && err.kind() == io::ErrorKind::NotFound => {
                warn!("Optional file config '{}' does not exist.", path.display());
                Ok(None)
            }
            Err(err) => Err(mk_parse_err(err, &path)),
        }
    }

    // Returns Ok(Some(val)) if the value exists.
    //   - If a trail is specified, the file is deserialized as a JSON/YAML/TOML dict and
    //     the value at that trail is returned.
    //   - If no trail is specified, the string content of the file is returned.
    // Returns Ok(None) if the request is optional and the file doesn't exist.
    // Returns an Err(ParseError) otherwise.
    fn read_value_from_file(
        &self,
        expansion_request: &ExpansionRequest,
    ) -> Result<Option<Val>, ParseError> {
        let path = self.build_root.join(&expansion_request.path);
        match self.read_content_from_file(expansion_request)? {
            Some(content) => {
                if let Some(trail) = &expansion_request.trail {
                    let dict =
                        try_deserialize::<HashMap<String, Val>>(content.as_str(), Some(&path))?;
                    if let Some(dict) = dict {
                        let val = follow_the_trail(Val::Dict(dict), trail.clone())
                            .map_err(|s| mk_parse_err(s, &path))?;
                        return Ok(Some(val));
                    }
                }
                Ok(Some(Val::String(content)))
            }
            None => Ok(None),
        }
    }

    pub(crate) fn expand<T: FromVal>(&self, value: String) -> Result<Option<T>, ParseError> {
        let (expansion_request_opt, value) = ExpansionRequest::from_value(value);
        let (path_opt, val_opt) = if let Some(expansion_request) = expansion_request_opt {
            self.read_value_from_file(&expansion_request)
                .map(|v| (Some(expansion_request.path), v))?
        } else {
            (None, Some(Val::String(value)))
        };

        val_opt
            .map(|val| {
                if let Val::String(s) = val {
                    T::parse(&s)
                } else {
                    T::from_val(&val).map_err(|e| {
                        if let Some(path) = path_opt {
                            mk_parse_err(e, &path)
                        } else {
                            ParseError::new(format!("Problem parsing value for {{name}}: {e}"))
                        }
                    })
                }
            })
            .transpose()
    }

    pub(crate) fn expand_to_list<T: FromVal>(
        &self,
        value: String,
    ) -> Result<Option<Vec<ListEdit<T>>>, ParseError> {
        // There are a few different ways of trying to get a list out of an option
        // value, and each might return a parsed list or a string that needs to be parsed.
        enum ListOrString<T> {
            List(Vec<T>),
            String(String),
            None,
        }

        let (expansion_request_opt, value) = ExpansionRequest::from_value(value);

        let list_or_string: ListOrString<T> = if let Some(expansion_request) = expansion_request_opt
        {
            if expansion_request.trail.is_some() {
                // The list is a subobject of some top-level dict.
                match self.read_value_from_file(&expansion_request)? {
                    Some(Val::List(list)) => ListOrString::List(
                        list.iter()
                            .map(T::from_val)
                            .collect::<Result<_, _>>()
                            .map_err(|e| mk_parse_err(e, &expansion_request.path))?,
                    ),
                    Some(Val::String(string)) => ListOrString::String(string),
                    other_val => Err(mk_parse_err(
                        format!("Couldn't interpret value `{:?}` as list", other_val),
                        &expansion_request.path,
                    ))?,
                }
            } else {
                // Try and directly parse a top-level JSON/YAML list ,falling back to parsing
                // as a literal.
                match self.read_content_from_file(&expansion_request) {
                    Ok(Some(content)) => {
                        match try_deserialize::<Vec<T>>(
                            content.as_str(),
                            Some(&expansion_request.path),
                        )? {
                            Some(list) => ListOrString::List(list),
                            None => ListOrString::String(content),
                        }
                    }
                    Ok(None) => ListOrString::None,
                    Err(e) => Err(e)?,
                }
            }
        } else {
            ListOrString::String(value)
        };

        match list_or_string {
            ListOrString::List(items) => Ok(Some(vec![ListEdit {
                action: ListEditAction::Replace,
                items,
            }])),
            ListOrString::String(string) => T::parse_list(&string).map(Some),
            ListOrString::None => Ok(None),
        }
    }

    pub(crate) fn expand_to_dict(
        &self,
        value: String,
    ) -> Result<Option<Vec<DictEdit>>, ParseError> {
        let (expansion_request_opt, value) = ExpansionRequest::from_value(value);
        if let Some(mut expansion_request) = expansion_request_opt {
            // In the specific case where we expect a dict value, if the file is parseable as
            // JSON/YAML/TOML and the user provided no trail then we know they mean the entire
            // dict, so set an empty trail to indicate that.
            if expansion_request.trail.is_none() {
                expansion_request = ExpansionRequest {
                    path: expansion_request.path,
                    trail: Some(vec![]),
                    optional: expansion_request.optional,
                };
            }
            self.read_value_from_file(&expansion_request)?
                .map(|val| match val {
                    Val::Dict(dict) => Ok(vec![DictEdit {
                        action: DictEditAction::Replace,
                        items: dict,
                    }]),
                    Val::String(string) => parse_dict(&string).map(|x| vec![x]),
                    other_val => Err(mk_parse_err(
                        format!("Couldn't interpret value `{:?}` as dict", other_val),
                        &expansion_request.path,
                    )),
                })
                .transpose()
        } else {
            parse_dict(&value).map(|x| Some(vec![x]))
        }
    }

    pub fn add_to_sha256(&self, hasher: &mut Sha256) {
        hasher.update(self.build_root.as_os_str().as_bytes());
    }
}

#[cfg(test)]
pub(crate) mod test_util {
    use std::fs::File;
    use std::io::Write;
    use std::path::PathBuf;
    use tempfile::{TempDir, tempdir};

    pub(crate) fn write_fromfile(filename: &str, content: &str) -> (TempDir, PathBuf) {
        let tmpdir = tempdir().unwrap();
        let fromfile_path = tmpdir.path().join(filename);
        let mut fromfile = File::create(&fromfile_path).unwrap();
        fromfile.write_all(content.as_bytes()).unwrap();
        fromfile.flush().unwrap();
        (tmpdir, fromfile_path)
    }
}
