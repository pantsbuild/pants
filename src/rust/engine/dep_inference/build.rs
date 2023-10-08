// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::unseparated_literal_suffix,
  clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::{collections::HashSet, io::Write, path::Path};
use std::{env, fs};
use walkdir::WalkDir;

/// The tree-sitter interfaces don't have nice constants that allow us to reference their magic numbers by name.
/// We generate those constants here.
/// Tree-sitter grammars don't have to give symbols unique names (in `ts_symbol_names`),
/// and there can be multiple symbols mapped to the same name.
/// For example, they might map both `block` and `_match_block` to "block" because one of those in internal
/// For most names, there will only be 1 symbol; for those, we create a const u16 for convenience.
/// For the names with multiple symbols, we generate a const array (hashmaps would have been nice, but I couldn't figure out how to make them const)
fn gen_constants_file(language: &tree_sitter::Language, out_dir: &Path) {
  let mut file = std::fs::File::create(out_dir.join("constants.rs")).unwrap();

  file
    .write_all(
      b"\
// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#[non_exhaustive]
pub struct KindID;

impl KindID {
",
    )
    .unwrap();

  let mut kinds_to_ids: HashMap<String, HashSet<u16>> = HashMap::new();

  // Collect the mapping of name->symbols
  for id in (0_u16..(language.node_kind_count() as u16))
    .chain([language.id_for_node_kind("ERROR", true)].iter().cloned())
  {
    if language.node_kind_is_named(id) {
      let kind = language.node_kind_for_id(id).unwrap().to_uppercase();
      kinds_to_ids
        .entry(kind)
        .or_default()
        .insert(id);
    }
  }

  // Codegen for each name->symbol mapping
  for (kind, ids) in kinds_to_ids {
    let text = match ids.len() {
      1 => {
        let single = ids.iter().next().unwrap();
        format!("  pub const {kind}: u16 = {single};\n")
      }
      _ => {
        let items: String = ids
          .iter()
          .map(|id| id.to_string())
          .collect::<Vec<String>>()
          .join(", ");
        format!(
          "  pub const {}: [u16; {}]  = [{}];\n",
          kind,
          ids.len(),
          items
        )
      }
    };
    file.write_all(text.as_bytes()).unwrap();
  }

  file.write_all(b"}\n").unwrap();
}

fn gen_visitor_file(language: &tree_sitter::Language, out_dir: &Path) {
  let mut file = std::fs::File::create(out_dir.join("visitor.rs")).unwrap();

  file
    .write_all(
      b"\
// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#[derive(Debug, PartialEq)]
pub enum ChildBehavior {
  Visit,
  Ignore,
}

#[allow(unused_variables)]
pub trait Visitor {
  fn walk(&mut self, cursor: &mut tree_sitter::TreeCursor) {
    loop {
      let node = cursor.node();
      let children_behavior = self.visit(node);

      if children_behavior == ChildBehavior::Visit && cursor.goto_first_child() {
        continue;
      }
      // NB: Could post_visit(node) here

      if cursor.goto_next_sibling() {
        continue;
      }

      let mut at_root = false;
      while !at_root {
        if cursor.goto_parent() {
          // NB: Could post_visit(cursor.node()) here
          if cursor.goto_next_sibling() {
            break;
          }
        } else {
          at_root = true
        }
      }
      if at_root {
        break;
      }
    }
  }
",
    )
    .unwrap();

  let mut kinds_seen = HashSet::new();
  for id in 0..language.node_kind_count() {
    let id = id as u16;
    if language.node_kind_is_named(id) {
      let kind = language.node_kind_for_id(id).unwrap();
      if kinds_seen.insert(kind) {
        file.write_all(
          format!("  fn visit_{kind}(&mut self, node: tree_sitter::Node) -> ChildBehavior {{\n    ChildBehavior::Visit\n  }}\n").as_bytes(),
        )
        .unwrap();
      }
    }
  }

  file
    .write_all(
      b"  fn visit(&mut self, node: tree_sitter::Node) -> ChildBehavior {
    match node.kind_id() {
",
    )
    .unwrap();
  for id in 0..language.node_kind_count() {
    let id = id as u16;
    if language.node_kind_is_named(id) {
      let kind = language.node_kind_for_id(id).unwrap();
      file
        .write_all(format!("    {id} =>   self.visit_{kind}(node),\n").as_bytes())
        .unwrap();
    }
  }
  file
    .write_all(
      b"      _ => ChildBehavior::Visit,
    }
  }
}
",
    )
    .unwrap();
}

fn gen_impl_hash_file(name: &'static str, source_dir: &Path, impl_dir: &Path, out_dir: &Path) {
  let mut hasher = Sha256::default();
  for entry in WalkDir::new(impl_dir)
    .sort_by_file_name()
    .into_iter()
    .chain(WalkDir::new(source_dir).sort_by_file_name().into_iter())
    .flatten()
  {
    if entry.file_type().is_file() && entry.path().file_name().unwrap() != "tests.rs" {
      let mut reader = std::fs::File::open(entry.path()).expect("Failed to open file");
      let _ = std::io::copy(&mut reader, &mut hasher).expect("Failed to copy bytes");
    }
  }
  hasher
    .write_all(env::var("CARGO_PKG_VERSION").unwrap().as_bytes())
    .unwrap();
  let hash_bytes = &hasher.finalize();
  let hash = hex::encode(hash_bytes);
  let mut file = std::fs::File::create(out_dir.join(format!("{name}_impl_hash.rs"))).unwrap();
  file
    .write_all(format!("pub const IMPL_HASH: &str = {hash:?};").as_bytes())
    .unwrap();
  if env::var_os("PANTS_PRINT_IMPL_HASHES") == Some("1".into()) {
    println!("cargo:warning={name} hash impl hash: {hash}");
  }
}

fn gen_files_for_language(
  language: tree_sitter::Language,
  name: &'static str,
  source_dir: &Path,
  out_dir: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
  let subdir = out_dir.join(name);
  fs::create_dir_all(&subdir)?;
  gen_constants_file(&language, subdir.as_path());
  gen_visitor_file(&language, subdir.as_path());

  // NB: This MUST be last in the list
  let source_subdir = source_dir.join(name);
  gen_impl_hash_file(name, source_subdir.as_path(), subdir.as_path(), out_dir);
  Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
  let source_dir = env::var_os("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR env var not set.");
  let source_dir = Path::new(&source_dir).join("src");
  let out_dir = env::var_os("OUT_DIR").expect("OUT_DIR env var not set.");
  let out_dir = Path::new(&out_dir);
  gen_files_for_language(
    tree_sitter_python::language(),
    "python",
    &source_dir,
    out_dir,
  )?;
  gen_files_for_language(
    tree_sitter_javascript::language(),
    "javascript",
    &source_dir,
    out_dir,
  )?;
  println!("cargo:rerun-if-env-changed=PANTS_PRINT_IMPL_HASHES");
  println!("cargo:rerun-if-changed=build.rs");
  println!("cargo:rerun-if-changed=src");
  Ok(())
}
