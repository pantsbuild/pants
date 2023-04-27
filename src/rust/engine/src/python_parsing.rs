// TODO:
// - Stron/weak
// - Support __import__
// - Support string imports
// - Support string assets
// - Support pragma

#![allow(dead_code)]
#![allow(unused_variables)]

use rustpython_ast::visitor::{ImportFromNode, ImportNode, Visitor};
use rustpython_ast::Alias;
use rustpython_parser::parse_program;
use std::collections::HashMap;
use std::path::PathBuf;

pub fn get_dependencies(
  contents: &str,
  filepath: PathBuf,
) -> Result<HashMap<String, (u64, bool)>, String> {
  let program = parse_program(contents, filepath.to_str().unwrap())
    .map_err(|e| format!("Failed to parse file <BLAH>: {e}"))?;

  let mut dep_visitor = DependencyExtractorVisitor::new(filepath);
  for stmt in program.iter() {
    dep_visitor.visit_stmt(stmt.clone());
  }

  Ok(dep_visitor.import_map)
}

pub struct DependencyExtractorVisitor {
  pub filepath: PathBuf,
  pub import_map: HashMap<String, (u64, bool)>,
  weaken_imports: bool,
}

impl DependencyExtractorVisitor {
  pub fn new(filepath: PathBuf) -> DependencyExtractorVisitor {
    DependencyExtractorVisitor {
      filepath,
      import_map: HashMap::new(),
      weaken_imports: false,
    }
  }

  fn add_dependency(&mut self, module: &Option<String>, alias: &Alias, level: &Option<usize>) {
    let mut mod_parts = Vec::new();
    let level = level.unwrap_or(0);
    if level > 0 {
      let extensionless = self.filepath.with_extension("");
      let mut path_parts: Vec<String> = extensionless
        .iter()
        .map(|p| p.to_str().unwrap().to_string())
        .collect();
      path_parts.truncate(path_parts.len() - level + 1);
      mod_parts.append(&mut path_parts);
    }
    if let Some(module) = module {
      mod_parts.push(module.clone());
    }
    mod_parts.push(alias.node.name.clone());

    let modname = mod_parts.join(".");
    self
      .import_map
      .insert(modname, (alias.location.row().try_into().unwrap(), false));
  }
}

impl Visitor for DependencyExtractorVisitor {
  fn visit_Import(&mut self, node: ImportNode) {
    for name in &node.node.names {
      self.add_dependency(&None, name, &None);
    }
    self.generic_visit_Import(node);
  }

  fn visit_ImportFrom(&mut self, node: ImportFromNode) {
    for name in &node.node.names {
      self.add_dependency(&node.node.module, name, &node.node.level);
    }
    self.generic_visit_ImportFrom(node);
  }
}

// =================================
