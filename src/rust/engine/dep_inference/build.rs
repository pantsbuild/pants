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

use std::{collections::HashSet, io::Write, path::Path};
use std::{env, fs};

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

  let mut kinds_seen = HashSet::new();

  for id in (0_u16..(language.node_kind_count() as u16))
    .chain([language.id_for_node_kind("ERROR", true)].iter().cloned())
  {
    if language.node_kind_is_named(id) {
      let kind = language.node_kind_for_id(id).unwrap().to_uppercase();
      if kinds_seen.insert(kind.clone()) {
        file
          .write_all(format!("  pub const {kind}: u16 = {id};\n").as_bytes())
          .unwrap();
      }
    }
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
        .write_all(format!("      {id} => self.visit_{kind}(node),\n").as_bytes())
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

fn gen_files_for_language(
  language: tree_sitter::Language,
  name: &'static str,
  out_dir: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
  let subdir = out_dir.join(name);
  fs::create_dir_all(&subdir)?;
  gen_constants_file(&language, subdir.as_path());
  gen_visitor_file(&language, subdir.as_path());
  Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
  let out_dir = env::var_os("OUT_DIR").expect("OUT_DIR env var not set.");
  let out_dir = Path::new(&out_dir);
  gen_files_for_language(tree_sitter_python::language(), "python", out_dir)?;
  gen_files_for_language(tree_sitter_javascript::language(), "javascript", out_dir)?;
  println!("cargo:rerun-if-env-changed=build.rs");
  Ok(())
}
