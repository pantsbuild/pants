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

use std::collections::HashMap;
use std::env;
use std::{collections::HashSet, io::Write, path::Path};

/// The tree-sitter interfaces don't have nice constants that allow us to reference their magic numbers by name.
/// We generate those constants here.
/// Tree-sitter grammars don't have to give symbols unique names (in `ts_symbol_names`),
/// and there can be multiple symbols mapped to the same name.
/// For example, they might map both `block` and `_match_block` to "block" because one of those in internal
/// For most names, there will only be 1 symbol; for those, we create a const u16 for convenience.
/// For the names with multiple symbols, we generate a const array (hashmaps would have been nice, but I couldn't figure out how to make them const)
fn gen_constants_file(language: &tree_sitter::Language, out_dir: &Path) {
    let mut file = std::fs::File::create(out_dir.join("constants.rs")).unwrap();

    file.write_all(
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
                .or_insert_with(HashSet::new)
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

fn gen_visitor_file(out_dir: &Path) {
    let mut file = std::fs::File::create(out_dir.join("visitor.rs")).unwrap();
    let python_lang = tree_sitter_python::language();

    file.write_all(
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

    file.write_all(
        b"  fn visit(&mut self, node: tree_sitter::Node) -> ChildBehavior {
    match node.kind_id() {
",
    )
    .unwrap();
    for id in 0..python_lang.node_kind_count() {
        let id = id as u16;
        if python_lang.node_kind_is_named(id) {
            let kind = python_lang.node_kind_for_id(id).unwrap();
            file.write_all(format!("      {id} => self.visit_{kind}(node),\n").as_bytes())
                .unwrap();
        }
    }
    file.write_all(
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
    gen_constants_file(&tree_sitter_python::language(), out_dir);
    gen_visitor_file(out_dir);
    println!("cargo:rerun-if-env-changed=build.rs");
}
