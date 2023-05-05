// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::{collections::HashSet, io::Write, path::PathBuf};

fn gen_constants_file() {
  let mut file = std::fs::File::create(PathBuf::from("src/python/constants.rs")).unwrap();

  file
    .write_all(b"// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).\n")
    .unwrap();
  file
    .write_all(b"// Licensed under the Apache License, Version 2.0 (see LICENSE).\n")
    .unwrap();
  file.write_all(b"\n// Generated \n").unwrap();

  file
    .write_all(b"#[non_exhaustive]\npub struct KindID;\n\n")
    .unwrap();
  file.write_all(b"impl KindID {\n").unwrap();

  let python_lang = tree_sitter_python::language();
  let mut kinds_seen = HashSet::new();

  for id in 0..python_lang.node_kind_count() {
    let id = id as u16;
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

fn gen_visitor_file() {
  let mut file = std::fs::File::create(PathBuf::from("src/python/visitor.rs")).unwrap();
  let python_lang = tree_sitter_python::language();

  file.write_all(b"// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).\n// Licensed under the Apache License, Version 2.0 (see LICENSE).\n").unwrap();

  file
    .write_all(
      br#"#[derive(Debug, PartialEq)]
pub enum ChildBehavior {
  Visit,
  Ignore,
}
"#,
    )
    .unwrap();

  file
    .write_all(b"#[allow(unused_variables)]\npub trait Visitor {\n")
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
    .write_all(b"\n  fn visit(&mut self, node: tree_sitter::Node) -> ChildBehavior {\n")
    .unwrap();
  file.write_all(b"    match node.kind_id() {\n").unwrap();
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
    .write_all(b"      _ => ChildBehavior::Visit,\n")
    .unwrap();
  file.write_all(b"    }\n").unwrap();
  file.write_all(b"  }\n").unwrap();
  file.write_all(b"}\n").unwrap();
}

fn main() {
  gen_constants_file();
  gen_visitor_file();
}
