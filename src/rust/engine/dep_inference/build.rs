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

use std::env;
use std::{collections::HashSet, io::Write, path::Path};

fn gen_constants_file(out_dir: &Path) {
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

  let python_lang = tree_sitter_python::language();
  let mut kinds_seen = HashSet::new();

  for id in (0_u16..(python_lang.node_kind_count() as u16)).chain(
    [python_lang.id_for_node_kind("ERROR", true)]
      .iter()
      .cloned(),
  ) {
    if python_lang.node_kind_is_named(id) {
      let kind = python_lang.node_kind_for_id(id).unwrap().to_uppercase();
      if kinds_seen.insert(kind.clone()) {
        file
          .write_all(format!("  pub const {kind}: u16 = {id};\n").as_bytes())
          .unwrap();
      }
    }
  }

  file.write_all(b"}\n").unwrap();
}

fn gen_visitor_file(out_dir: &Path) {
  let mut file = std::fs::File::create(out_dir.join("visitor.rs")).unwrap();
  let python_lang = tree_sitter_python::language();

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
  for id in 0..python_lang.node_kind_count() {
    let id = id as u16;
    if python_lang.node_kind_is_named(id) {
      let kind = python_lang.node_kind_for_id(id).unwrap();
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
  for id in 0..python_lang.node_kind_count() {
    let id = id as u16;
    if python_lang.node_kind_is_named(id) {
      let kind = python_lang.node_kind_for_id(id).unwrap();
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

fn main() {
  let out_dir = env::var_os("OUT_DIR").unwrap();
  let out_dir = Path::new(&out_dir);
  gen_constants_file(out_dir);
  gen_visitor_file(out_dir);
  println!("cargo:rerun-if-env-changed=build.rs");
}
