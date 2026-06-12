// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::path::Path;

use deepsize::DeepSizeOf;
use fs::{
    self, DigestEntry, DirectoryDigest, FileContent, FileEntry, GlobMatching, PathGlobs,
    PreparedPathGlobs, SymlinkBehavior, SymlinkEntry,
};
use futures::TryFutureExt;
use graph::CompoundNode;
use pyo3::Bound;
use pyo3::prelude::{Py, PyAny, PyAnyMethods, Python};

use super::{NodeKey, NodeOutput, NodeResult, unmatched_globs_additional_context};
use crate::context::Context;
use crate::externs;
use crate::python::{Value, throw};

///
/// A Node that captures an store::Snapshot for a PathGlobs subject.
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct Snapshot {
    pub(super) path_globs: PathGlobs,
}

impl Snapshot {
    pub fn from_path_globs(path_globs: PathGlobs) -> Snapshot {
        Snapshot { path_globs }
    }

    pub fn lift_path_globs(item: &Bound<'_, PyAny>) -> Result<PathGlobs, String> {
        let py_path_globs: pyo3::PyRef<externs::fs::PyPathGlobs> = item
            .extract()
            .map_err(|e| format!("Expected a PathGlobs instance: {e}"))?;
        Ok(PathGlobs::clone(&py_path_globs))
    }

    pub fn lift_prepared_path_globs(item: &Bound<'_, PyAny>) -> Result<PreparedPathGlobs, String> {
        let path_globs = Snapshot::lift_path_globs(item)?;
        path_globs
            .parse()
            .map_err(|e| format!("Failed to parse PathGlobs for globs({item:?}): {e}"))
    }

    pub fn store_directory_digest(py: Python, item: DirectoryDigest) -> Result<Value, String> {
        let py_digest = Py::new(py, externs::fs::PyDigest(item)).map_err(|e| format!("{e}"))?;
        Ok(Value::new(py_digest.into_any()))
    }

    pub fn store_file_digest(py: Python, item: hashing::Digest) -> Result<Value, String> {
        let py_file_digest =
            Py::new(py, externs::fs::PyFileDigest(item)).map_err(|e| format!("{e}"))?;
        Ok(Value::new(py_file_digest.into_any()))
    }

    pub fn store_snapshot(py: Python, item: store::Snapshot) -> Result<Value, String> {
        let py_snapshot = Py::new(py, externs::fs::PySnapshot(item)).map_err(|e| format!("{e}"))?;
        Ok(Value::new(py_snapshot.into_any()))
    }

    pub fn store_path(py: Python, item: &Path) -> Result<Value, String> {
        if let Some(p) = item.as_os_str().to_str() {
            Ok(externs::store_utf8(py, p))
        } else {
            Err(format!("Could not decode path `{item:?}` as UTF8."))
        }
    }

    fn store_file_content(
        py: Python,
        types: &crate::types::Types,
        item: &FileContent,
    ) -> Result<Value, String> {
        Ok(externs::unsafe_call(
            py,
            types.file_content,
            &[
                Self::store_path(py, &item.path)?,
                externs::store_bytes(py, &item.content),
                externs::store_bool(py, item.is_executable),
            ],
        ))
    }

    fn store_file_entry(
        py: Python,
        types: &crate::types::Types,
        item: &FileEntry,
    ) -> Result<Value, String> {
        Ok(externs::unsafe_call(
            py,
            types.file_entry,
            &[
                Self::store_path(py, &item.path)?,
                Self::store_file_digest(py, item.digest)?,
                externs::store_bool(py, item.is_executable),
            ],
        ))
    }

    fn store_symlink_entry(
        py: Python,
        types: &crate::types::Types,
        item: &SymlinkEntry,
    ) -> Result<Value, String> {
        Ok(externs::unsafe_call(
            py,
            types.symlink_entry,
            &[
                Self::store_path(py, &item.path)?,
                externs::store_utf8(py, item.target.to_str().unwrap()),
            ],
        ))
    }

    fn store_empty_directory(
        py: Python,
        types: &crate::types::Types,
        path: &Path,
    ) -> Result<Value, String> {
        Ok(externs::unsafe_call(
            py,
            types.directory,
            &[Self::store_path(py, path)?],
        ))
    }

    pub fn store_digest_contents(
        py: Python,
        context: &Context,
        item: &[FileContent],
    ) -> Result<Value, String> {
        let entries = item
            .iter()
            .map(|e| Self::store_file_content(py, &context.core.types, e))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(externs::unsafe_call(
            py,
            context.core.types.digest_contents,
            &[externs::store_tuple(py, entries)
                .map_err(|e| format!("PyTuple construction failure: {e:?}"))?],
        ))
    }

    pub fn store_digest_entries(
        py: Python,
        context: &Context,
        item: &[DigestEntry],
    ) -> Result<Value, String> {
        let entries = item
            .iter()
            .map(|digest_entry| match digest_entry {
                DigestEntry::File(file_entry) => {
                    Self::store_file_entry(py, &context.core.types, file_entry)
                }
                DigestEntry::Symlink(symlink_entry) => {
                    Self::store_symlink_entry(py, &context.core.types, symlink_entry)
                }
                DigestEntry::EmptyDirectory(path) => {
                    Self::store_empty_directory(py, &context.core.types, path)
                }
            })
            .collect::<Result<Vec<_>, _>>()?;
        Ok(externs::unsafe_call(
            py,
            context.core.types.digest_entries,
            &[externs::store_tuple(py, entries)
                .map_err(|e| format!("PyTuple construction faiure: {e:?}"))?],
        ))
    }

    pub(super) async fn run_node(self, context: Context) -> NodeResult<store::Snapshot> {
        let path_globs = self.path_globs.parse().map_err(throw)?;

        // We rely on Context::expand_globs to track dependencies for scandirs,
        // and `context.get(DigestFile)` to track dependencies for file digests.
        let path_stats = context
            .expand_globs(
                path_globs,
                SymlinkBehavior::Oblivious,
                unmatched_globs_additional_context(),
            )
            .await?;

        store::Snapshot::from_path_stats(context.clone(), path_stats)
            .map_err(|e| throw(format!("Snapshot failed: {e}")))
            .await
    }
}

impl CompoundNode<NodeKey> for Snapshot {
    type Item = store::Snapshot;
}

impl From<Snapshot> for NodeKey {
    fn from(n: Snapshot) -> Self {
        NodeKey::Snapshot(n)
    }
}

impl TryFrom<NodeOutput> for store::Snapshot {
    type Error = ();

    fn try_from(nr: NodeOutput) -> Result<Self, ()> {
        match nr {
            NodeOutput::Snapshot(v) => Ok(v),
            _ => Err(()),
        }
    }
}
