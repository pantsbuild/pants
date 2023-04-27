// TODO:
// - Support string imports
// - Support string assets

#![allow(dead_code)]
#![allow(unused_variables)]

use rustpython_ast::visitor::{
  CallNode, ImportFromNode, ImportNode, TryNode, TryStarNode, Visitor,
};
use rustpython_ast::{Alias, Constant, Excepthandler, ExcepthandlerKind, ExprKind, Stmt};
use rustpython_parser::parse_program;
use std::collections::HashMap;
use std::path::PathBuf;

pub fn get_dependencies(
  contents: &str,
  filepath: PathBuf,
) -> Result<HashMap<String, (u64, bool)>, String> {
  let program = parse_program(contents, filepath.to_str().unwrap())
    .map_err(|e| format!("Failed to parse file {filepath:?}: {e}"))?;

  let mut visitor = DependencyExtractorVisitor::new(filepath.clone());
  for stmt in program.iter() {
    visitor.visit_stmt(stmt.clone());
  }

  // Remove entries whose row includes "# pants: no-infer-dep"
  let contents_string = contents.to_string();
  let lines: Vec<_> = contents_string.lines().collect();
  visitor
    .import_map
    .retain(|_, &mut (line, _)| lines[line as usize].contains("# pants: no-infer-dep"));

  Ok(visitor.import_map)
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

    self.import_map.insert(
      modname,
      (
        alias.location.row().try_into().unwrap(),
        self.weaken_imports,
      ),
    );
  }

  fn visit_try(&mut self, handlers: &Vec<Excepthandler>, body: Vec<Stmt>) {
    // N.B. Python allows any arbitrary expression as an except handler.
    // We only parse Name, or (Set/Tuple/List)-of-Names expressions
    for handler in handlers {
      let maybe_type_ = match &handler.node {
        ExcepthandlerKind::ExceptHandler { type_, .. } => type_,
      };
      if let Some(type_) = maybe_type_ {
        let type_ = *type_.clone();
        let exprs = match &type_.node {
          ExprKind::Name { .. } => vec![type_],
          ExprKind::Set { elts } | ExprKind::List { elts, .. } | ExprKind::Tuple { elts, .. } => {
            elts.clone()
          }
          _ => Vec::new(),
        };
        for expr in exprs {
          if let ExprKind::Name { id, .. } = expr.node {
            // @TODO: Add "ModuleNotFoundError" to this list
            if id == *"ImportError".to_string() {
              self.weaken_imports = true;
              break;
            }
          }
        }
      }
    }

    for value in body {
      self.visit_stmt(value);
    }

    self.weaken_imports = false;
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

  fn visit_Call(&mut self, node: CallNode) {
    // Handle __import__("string_literal").  This is commonly used in __init__.py files,
    // to explicitly mark namespace packages.  Note that we don't handle more complex
    // uses, such as those that set `level`.
    if let ExprKind::Name { id, .. } = &node.node.func.node {
      if *id == *"__import__".to_string() && node.node.args.len() == 1 {
        let arg = &node.node.args[0];
        if let ExprKind::Constant {
          value: Constant::Str(string),
          ..
        } = &arg.node
        {
          self.import_map.insert(
            string.clone(),
            (arg.location.row().try_into().unwrap(), false),
          );
        }
      }
    }

    self.generic_visit_Call(node);
  }

  fn visit_Try(&mut self, node: TryNode) {
    self.visit_try(&node.node.handlers, node.node.body);

    // visit_try visits the body, and leaves the rest to us
    for value in node.node.handlers {
      self.visit_excepthandler(value);
    }
    for value in node.node.orelse {
      self.visit_stmt(value);
    }
    for value in node.node.finalbody {
      self.visit_stmt(value);
    }
  }

  fn visit_TryStar(&mut self, node: TryStarNode) {
    self.visit_try(&node.node.handlers, node.node.body);

    // visit_try visits the body, and leaves the rest to us
    for value in node.node.handlers {
      self.visit_excepthandler(value);
    }
    for value in node.node.orelse {
      self.visit_stmt(value);
    }
    for value in node.node.finalbody {
      self.visit_stmt(value);
    }
  }
}
