// TODO:
// - Stron/weak
// - Support __import__
// - Support string imports
// - Support string assets
// - Support pragma

#![allow(dead_code)]
#![allow(unused_variables)]

use rustpython_parser::parser::parse_program;
use std::collections::HashMap;
use std::path::PathBuf;

fn get_dependencies(
  contents: &str,
  filepath: PathBuf,
) -> Result<HashMap<String, (u64, bool)>, String> {
  let program = parse_program(contents, filepath.to_str().unwrap())
    .map_err(|e| format!("Failed to parse file <BLAH>: {e}"))?;

  let mut dep_visitor = DependencyExtractorVisitor::new(filepath);
  for stmt in program.iter() {
    dep_visitor.visit_stmt(stmt);
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
}

impl Visitor<'_> for DependencyExtractorVisitor {
  fn visit_import(&mut self, module: Option<String>, alias: Alias, level: Option<usize>) {
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
      mod_parts.push(module);
    }
    mod_parts.push(alias.node.name.clone());

    let modname = mod_parts.join(".");
    self
      .import_map
      .insert(modname, (alias.location.row().try_into().unwrap(), false));
  }
}

// =================================

use rustpython_parser::ast::{
  Alias, Arg, Arguments, Boolop, Cmpop, Comprehension, Constant, Excepthandler, ExcepthandlerKind,
  Expr, ExprContext, ExprKind, Keyword, MatchCase, Operator, Pattern, PatternKind, Stmt, StmtKind,
  Unaryop, Withitem,
};

pub trait Visitor<'a> {
  fn visit_FunctionDef(&mut self, node: &'a StmtKind::FunctionDef) {
    self.generic_visit_FunctionDef(node);
  }
  fn visit_AsyncFunctionDef(&mut self, node: &'a StmtKind::AsyncFunctionDef) {
    self.generic_visit_AsyncFunctionDef(node);
  }
  fn visit_ClassDef(&mut self, node: &'a StmtKind::ClassDef) {
    self.generic_visit_ClassDef(node);
  }
  fn visit_Return(&mut self, node: &'a StmtKind::Return) {
    self.generic_visit_Return(node);
  }
  fn visit_Delete(&mut self, node: &'a StmtKind::Delete) {
    self.generic_visit_Delete(node);
  }
  fn visit_Assign(&mut self, node: &'a StmtKind::Assign) {
    self.generic_visit_Assign(node);
  }
  fn visit_AugAssign(&mut self, node: &'a StmtKind::AugAssign) {
    self.generic_visit_AugAssign(node);
  }
  fn visit_AnnAssign(&mut self, node: &'a StmtKind::AnnAssign) {
    self.generic_visit_AnnAssign(node);
  }
  fn visit_For(&mut self, node: &'a StmtKind::For) {
    self.generic_visit_For(node);
  }
  fn visit_AsyncFor(&mut self, node: &'a StmtKind::AsyncFor) {
    self.generic_visit_AsyncFor(node);
  }
  fn visit_While(&mut self, node: &'a StmtKind::While) {
    self.generic_visit_While(node);
  }
  fn visit_If(&mut self, node: &'a StmtKind::If) {
    self.generic_visit_If(node);
  }
  fn visit_With(&mut self, node: &'a StmtKind::With) {
    self.generic_visit_With(node);
  }
  fn visit_AsyncWith(&mut self, node: &'a StmtKind::AsyncWith) {
    self.generic_visit_AsyncWith(node);
  }
  fn visit_Match(&mut self, node: &'a StmtKind::Match) {
    self.generic_visit_Match(node);
  }
  fn visit_Raise(&mut self, node: &'a StmtKind::Raise) {
    self.generic_visit_Raise(node);
  }
  fn visit_Try(&mut self, node: &'a StmtKind::Try) {
    self.generic_visit_Try(node);
  }
  //fn visit_TryStar(&mut self, node: &'a StmtKind::TryStar){self.generic_visit_TryStar(node);}
  fn visit_Assert(&mut self, node: &'a StmtKind::Assert) {
    self.generic_visit_Assert(node);
  }
  fn visit_Import(&mut self, node: &'a StmtKind::Import) {
    self.generic_visit_Import(node);
  }
  fn visit_ImportFrom(&mut self, node: &'a StmtKind::ImportFrom) {
    self.generic_visit_ImportFrom(node);
  }
  fn visit_Expr(&mut self, node: &'a StmtKind::Expr) {
    self.generic_visit_Expr(node);
  }
  fn visit_NamedExpr(&mut self, node: &'a ExprKind::NamedExpr) {
    self.generic_visit_NamedExpr(node);
  }
  fn visit_BoolOp(&mut self, node: &'a ExprKind::BoolOp) {
    self.generic_visit_BoolOp(node);
  }
  fn visit_UnaryOp(&mut self, node: &'a ExprKind::UnaryOp) {
    self.generic_visit_UnaryOp(node);
  }
  fn visit_BinOp(&mut self, node: &'a ExprKind::BinOp) {
    self.generic_visit_BinOp(node);
  }
  fn visit_IfExp(&mut self, node: &'a ExprKind::IfExp) {
    self.generic_visit_IfExp(node);
  }
  fn visit_Dict(&mut self, node: &'a ExprKind::Dict) {
    self.generic_visit_Dict(node);
  }
  fn visit_Lambda(&mut self, node: &'a ExprKind::Lambda) {
    self.generic_visit_Lambda(node);
  }
  fn visit_ListComp(&mut self, node: &'a ExprKind::ListComp) {
    self.generic_visit_ListComp(node);
  }
  fn visit_Set(&mut self, node: &'a ExprKind::Set) {
    self.generic_visit_Set(node);
  }
  fn visit_DictComp(&mut self, node: &'a ExprKind::DictComp) {
    self.generic_visit_DictComp(node);
  }
  fn visit_SetComp(&mut self, node: &'a ExprKind::SetComp) {
    self.generic_visit_SetComp(node);
  }
  fn visit_Await(&mut self, node: &'a ExprKind::Await) {
    self.generic_visit_Await(node);
  }
  fn visit_GeneratorExp(&mut self, node: &'a ExprKind::GeneratorExp) {
    self.generic_visit_GeneratorExp(node);
  }
  fn visit_YieldFrom(&mut self, node: &'a ExprKind::YieldFrom) {
    self.generic_visit_YieldFrom(node);
  }
  fn visit_Yield(&mut self, node: &'a ExprKind::Yield) {
    self.generic_visit_Yield(node);
  }
  fn visit_Compare(&mut self, node: &'a ExprKind::Compare) {
    self.generic_visit_Compare(node);
  }
  fn visit_FormattedValue(&mut self, node: &'a ExprKind::FormattedValue) {
    self.generic_visit_FormattedValue(node);
  }
  fn visit_Call(&mut self, node: &'a ExprKind::Call) {
    self.generic_visit_Call(node);
  }
  fn visit_Constant(&mut self, node: &'a ExprKind::Constant) {
    self.generic_visit_Constant(node);
  }
  fn visit_JoinedStr(&mut self, node: &'a ExprKind::JoinedStr) {
    self.generic_visit_JoinedStr(node);
  }
  fn visit_Subscript(&mut self, node: &'a ExprKind::Subscript) {
    self.generic_visit_Subscript(node);
  }
  fn visit_Attribute(&mut self, node: &'a ExprKind::Attribute) {
    self.generic_visit_Attribute(node);
  }
  fn visit_Name(&mut self, node: &'a ExprKind::Name) {
    self.generic_visit_Name(node);
  }
  fn visit_Starred(&mut self, node: &'a ExprKind::Starred) {
    self.generic_visit_Starred(node);
  }
  fn visit_Tuple(&mut self, node: &'a ExprKind::Tuple) {
    self.generic_visit_Tuple(node);
  }
  fn visit_List(&mut self, node: &'a ExprKind::List) {
    self.generic_visit_List(node);
  }
  fn visit_excepthandler(&mut self, node: &'a ExceptHandler) {
    self.generic_visit_excepthandler(node);
  }
  fn visit_Slice(&mut self, node: &'a ExprKind::Slice) {
    self.generic_visit_Slice(node);
  }
  fn visit_arguments(&mut self, node: &'a Arguments) {
    self.generic_visit_arguments(node);
  }
  fn visit_comprehension(&mut self, node: &'a Comprehension) {
    self.generic_visit_comprehension(node);
  }
  fn visit_keyword(&mut self, node: &'a Keyword) {
    self.generic_visit_keyword(node);
  }
  fn visit_arg(&mut self, node: &'a Arg) {
    self.generic_visit_arg(node);
  }
  fn visit_withitem(&mut self, node: &'a WithItem) {
    self.generic_visit_withitem(node);
  }
  fn visit_pattern(&mut self, node: &'a Pattern) {
    self.generic_visit_pattern(node);
  }
  fn visit_match_case(&mut self, node: &'a MatchCase) {
    self.generic_visit_match_case(node);
  }
  fn visit_MatchSingleton(&mut self, node: &'a PatternKind::MatchSingleton) {
    self.generic_visit_MatchSingleton(node);
  }
  fn visit_MatchValue(&mut self, node: &'a PatternKind::MatchValue) {
    self.generic_visit_MatchValue(node);
  }
  fn visit_MatchMapping(&mut self, node: &'a PatternKind::MatchMapping) {
    self.generic_visit_MatchMapping(node);
  }
  fn visit_MatchSequence(&mut self, node: &'a PatternKind::MatchSequence) {
    self.generic_visit_MatchSequence(node);
  }
  fn visit_MatchClass(&mut self, node: &'a PatternKind::MatchClass) {
    self.generic_visit_MatchClass(node);
  }
  fn visit_MatchOr(&mut self, node: &'a PatternKind::MatchOr) {
    self.generic_visit_MatchOr(node);
  }
  fn visit_MatchAs(&mut self, node: &'a PatternKind::MatchAs) {
    self.generic_visit_MatchAs(node);
  }

  fn generic_visit_FunctionDef(&mut self, node: &'a StmtKind::FunctionDef) {
    self.visit_arguments(node.arguments);
    self.visit_stmts(node.body);
    self.visit_exprs(&node.decorator_list);
    if Some(returns) = node.returns {
      self.visit_exprs(&returns);
    }
  }

  fn generic_visit_AsyncFunctionDef(&mut self, node: &'a StmtKind::AsyncFunctionDef) {
    self.visit_arguments(node.arguments);
    self.visit_stmts(node.body);
    self.visit_exprs(&node.decorator_list);
    if Some(returns) = node.returns {
      self.visit_exprs(&returns);
    }
  }

  fn generic_visit_ClassDef(&mut self, node: &'a StmtKind::ClassDef) {
    self.visit_exprs(&node.bases);
    self.visit_keywords(node.keywords);
    self.visit_stmts(node.body);
    self.visit_exprs(&node.decorator_list);
  }

  fn generic_visit_Return(&mut self, node: &'a StmtKind::Return) {
    if Some(value) = node.value {
      self.visit_expr(annotation);
    }
  }

  fn generic_visit_Delete(&mut self, node: &'a StmtKind::Delete) {
    self.visit_exprs(&node.targets);
  }

  fn generic_visit_Assign(&mut self, node: &'a StmtKind::Assign) {
    self.visit_exprs(&node.targets);
    self.visit_expr(node.value);
  }
  fn generic_visit_AugAssign(&mut self, node: &'a StmtKind::AugAssign) {
    self.visit_expr(node.target);
    self.visit_expr(node.value);
  }
  fn generic_visit_AnnAssign(&mut self, node: &'a StmtKind::AnnAssign) {
    self.visit_expr(node.target);
    self.visit_expr(node.annotation);
    if Some(value) = node.value {
      self.visit_expr(value);
    }
  }
  fn generic_visit_For(&mut self, node: &'a StmtKind::For) {
    self.visit_expr(node.target);
    self.visit_expr(node.iter);
    self.visit_stmts(node.body);
    self.visit_stmts(node.orelse);
  }
  fn generic_visit_AsyncFor(&mut self, node: &'a StmtKind::AsyncFor) {
    self.visit_expr(node.target);
    self.visit_expr(node.iter);
    self.visit_stmts(node.body);
    self.visit_stmts(node.orelse);
  }
  fn generic_visit_While(&mut self, node: &'a StmtKind::While) {
    self.visit_expr(node.test);
    self.visit_stmts(node.body);
    self.visit_stmts(node.orelse);
  }
  fn generic_visit_If(&mut self, node: &'a StmtKind::If) {
    self.visit_expr(node.test);
    self.visit_stmts(node.body);
    self.visit_stmts(node.orelse);
  }
  fn generic_visit_With(&mut self, node: &'a StmtKind::With) {
    for item in node.items {
      self.visit_withitem(item);
    }
    self.visit_stmts(node.body);
  }
  fn generic_visit_AsyncWith(&mut self, node: &'a StmtKind::AsyncWith) {
    for item in node.items {
      self.visit_withitem(item);
    }
    self.visit_stmts(node.body);
  }
  fn generic_visit_Match(&mut self, node: &'a StmtKind::Match) {
    self.visit_expr(node.subject);
    for case in node.cases {
      self.visit_match_case(case);
    }
  }
  fn generic_visit_Raise(&mut self, node: &'a StmtKind::Raise) {
    if Some(exc) = node.exc {
      self.visit_expr(exc);
    }
    if Some(cause) = node.cause {
      self.visit_expr(cause);
    }
  }
  fn generic_visit_Try(&mut self, node: &'a StmtKind::Try) {
    self.visit_stmts(node.body);
    for handler in node.handlers {
      self.visit_excepthandler(handler);
    }
    self.visit_stmts(node.orelse);
    self.visit_stmts(node.finalbody);
  }
  // fn generic_visit_TryStar(&mut self, node: &'a StmtKind::TryStar) {
  //   self.visit_stmts(node.body);
  //   for handler in node.handlers {
  //     self.visit_excepthandler(handler);
  //   }
  //   self.visit_stmts(node.orelse);
  //   self.visit_stmts(node.finalbody);
  // }
  fn generic_visit_Assert(&mut self, node: &'a StmtKind::Assert) {
    self.visit_expr(node.test);
    if Some(msg) = node.msg {
      self.visit_expr(msg);
    }
  }
  fn generic_visit_Import(&mut self, node: &'a StmtKind::Import) {
    for alias in node.names {
      self.visit_alias(alias);
    }
  }
  fn generic_visit_ImportFrom(&mut self, node: &'a StmtKind::ImportFrom) {
    for alias in node.names {
      self.visit_alias(alias);
    }
  }
  fn visit_Global(&mut self, node: &'a StmtKind::Global) {
    self.generic_visit_Global(node);
  }
  fn generic_visit_Global(&mut self, node: &'a StmtKind::Global) {}
  fn visit_Nonlocal(&mut self, node: &'a StmtKind::Nonlocal) {
    self.generic_visit_Nonlocal(node);
  }
  fn generic_visit_Nonlocal(&mut self, node: &'a StmtKind::Nonlocal) {}
  fn generic_visit_Expr(&mut self, node: &'a StmtKind::Expr) {
    self.visit_expr(node.value);
  }
  fn visit_Pass(&mut self, node: &'a StmtKind::Pass) {
    self.generic_visit_Pass(node);
  }
  fn generic_visit_Pass(&mut self, node: &'a StmtKind::Pass) {}
  fn visit_Break(&mut self, node: &'a StmtKind::Break) {
    self.generic_visit_Break(node);
  }
  fn generic_visit_Break(&mut self, node: &'a StmtKind::Break) {}
  fn visit_Continue(&mut self, node: &'a StmtKind::Continue) {
    self.generic_visit_Continue(node);
  }
  fn generic_visit_Continue(&mut self, node: &'a StmtKind::Continue) {}

  fn generic_visit_BoolOp(&mut self, node: &'a ExprKind::BoolOp) {
    self.visit_boolop(node.op);
    self.visit_exprs(&node.values);
  }
  fn generic_visit_NamedExpr(&mut self, node: &'a ExprKind::NamedExpr) {
    self.visit_expr(node.target);
    self.visit_expr(node.value);
  }
  fn generic_visit_BinOp(&mut self, node: &'a ExprKind::BinOp) {
    self.visit_expr(self.left);
    self.visit_binop(self.op);
    self.visit_expr(self.right);
  }
  fn generic_visit_UnaryOp(&mut self, node: &'a ExprKind::UnaryOp) {
    self.visit_unaryop(self.op);
    self.visit_expr(self.operand);
  }
  fn generic_visit_Lambda(&mut self, node: &'a ExprKind::Lambda) {
    self.visit_arguments(node.args);
    self.visit_expr(node.body);
  }
  fn generic_visit_IfExp(&mut self, node: &'a ExprKind::IfExp) {
    self.visit_expr(node.test);
    self.visit_expr(node.body);
    self.visit_expr(node.orelse);
  }
  fn generic_visit_Dict(&mut self, node: &'a ExprKind::Dict) {
    for maybe_key in node.keys {
      if Some(key) = maybe_key {
        self.visit_expr(key);
      }
    }
    self.visit_exprs(&node.value);
  }
  fn generic_visit_Set(&mut self, node: &'a ExprKind::Set) {
    self.visit_exprs(&node.elts);
  }
  fn generic_visit_ListComp(&mut self, node: &'a ExprKind::ListComp) {
    self.visit_expr(node.elt);
    self.visit_comprehensions(node.generators);
  }
  fn generic_visit_SetComp(&mut self, node: &'a ExprKind::SetComp) {
    self.visit_expr(node.elt);
    self.visit_comprehensions(node.generators);
  }
  fn generic_visit_DictComp(&mut self, node: &'a ExprKind::DictComp) {
    self.visit_expr(node.key);
    self.visit_expr(node.value);
    self.visit_comprehensions(node.generators);
  }
  fn generic_visit_GeneratorExp(&mut self, node: &'a ExprKind::GeneratorExp) {
    self.visit_expr(node.elt);
    self.visit_comprehensions(node.generators);
  }
  fn generic_visit_Await(&mut self, node: &'a ExprKind::Await) {
    self.visit_expr(node.value);
  }
  fn generic_visit_Yield(&mut self, node: &'a ExprKind::Yield) {
    if Some(value) = node.value {
      self.visit_expr(value);
    }
  }
  fn generic_visit_YieldFrom(&mut self, node: &'a ExprKind::YieldFrom) {
    self.visit_expr(node.value);
  }
  fn generic_visit_Compare(&mut self, node: &'a ExprKind::Compare) {
    self.visit_expr(node.left);
    for cmpop in node.ops {
      self.visit_cmpop(cmpop);
    }
    self.visit_exprs(&node.comparators);
  }
  fn generic_visit_Call(&mut self, node: &'a ExprKind::Call) {
    self.visit_expr(node.func);
    self.visit_exprs(&node.args);
    self.visit_keywords(node.keywords);
  }
  fn generic_visit_FormattedValue(&mut self, node: &'a ExprKind::FormattedValue) {
    self.visit_expr(value);
    if Some(format_spec) = node.format_spec {
      self.visit_expr(format_spec);
    }
  }
  fn generic_visit_JoinedStr(&mut self, node: &'a ExprKind::JoinedStr) {
    self.visit_exprs(&node.value);
  }
  fn generic_visit_Constant(&mut self, node: &'a ExprKind::Constant) {
    // @TODO: WTF constant?!
  }
  fn generic_visit_Attribute(&mut self, node: &'a ExprKind::Attribute) {
    self.visit_expr(node.value);
    self.visit_exprcontext(node.ctx);
  }
  fn generic_visit_Subscript(&mut self, node: &'a ExprKind::Subscript) {
    self.visit_expr(node.value);
    self.visit_expr(node.slice);
    self.visit_exprcontext(node.ctx);
  }
  fn generic_visit_Starred(&mut self, node: &'a ExprKind::Starred) {
    self.visit_expr(node.value);
    self.visit_exprcontext(node.ctx);
  }
  fn generic_visit_Name(&mut self, node: &'a ExprKind::Name) {
    self.visit_exprcontext(node.ctx);
  }
  fn generic_visit_List(&mut self, node: &'a ExprKind::List) {
    self.visit_exprs(&node.elts);
    self.visit_exprcontext(node.ctx);
  }
  fn generic_visit_Tuple(&mut self, node: &'a ExprKind::Tuple) {
    self.visit_exprs(&node.elts);
    self.visit_exprcontext(node.ctx);
  }
  fn generic_visit_Slice(&mut self, node: &'a ExprKind::Slice) {
    if Some(lower) = node.lower {
      self.visit_expr(lower);
    }
    if Some(upper) = node.upper {
      self.visit_expr(upper);
    }
    if Some(step) = node.step {
      self.visit_expr(step);
    }
  }

  fn generic_visit_excepthandler(&mut self, node: &'a ExceptHandler) {
    match node.node {
      ExcepthandlerKind::ExceptHandler(node) => {
        if Some(type_) = node.type_ {
          self.visit_expr(type_);
        }
        self.visit_stmts(node.body);
      }
    }
  }

  fn visit_expr_context(&mut self, node: &'a ExprContext) {
    self.generic_visit_expr_context(node);
  }
  fn generic_visit_expr_context(&mut self, node: &'a ExprContext) {}
  fn visit_boolop(&mut self, node: &'a BoolOp) {
    self.generic_visit_boolop(node);
  }
  fn generic_visit_boolop(&mut self, node: &'a BoolOp) {}
  fn visit_operator(&mut self, node: &'a Operator) {
    self.generic_visit_operator(node);
  }
  fn generic_visit_operator(&mut self, node: &'a Operator) {}
  fn visit_unaryop(&mut self, node: &'a UnaryOp) {
    self.generic_visit_unaryop(node);
  }
  fn generic_visit_unaryop(&mut self, node: &'a UnaryOp) {}
  fn visit_cmpop(&mut self, node: &'a CmpOp) {
    self.generic_visit_cmpop(node);
  }
  fn generic_visit_cmpop(&mut self, node: &'a CmpOp) {}

  fn generic_visit_comprehension(&mut self, node: &'a Comprehension) {
    self.visit_expr(node.target);
    self.visit_expr(node.iter);
    self.visit_exprs(&node.ifs);
  }

  fn generic_visit_arguments(&mut self, node: &'a Arguments) {
    for arg in &node.posonlyargs {
      self.visit_arg(arg);
    }
    for arg in &node.args {
      self.visit_arg(arg);
    }
    if let Some(arg) = &node.vararg {
      self.visit_arg(arg);
    }
    for arg in &node.kwonlyargs {
      self.visit_arg(arg);
    }
    self.visit_exprs(&node.kw_defaults);
    if let Some(arg) = &arguments.kwarg {
      self.visit_arg(arg);
    }
    self.visit_exprs(&node.defaults);
  }

  fn generic_visit_arg(&mut self, node: &'a Arg) {
    if Some(annotation) = node.annotation {
      self.visit_expr(annotation);
    }
  }

  fn generic_visit_keyword(&mut self, node: &'a Keyword) {
    self.visit_expr(node.value);
  }

  fn visit_alias(&mut self, node: &'a Alias) {
    self.generic_visit_alias(node);
  }
  fn generic_visit_alias(&mut self, node: &'a Alias) {}

  fn generic_visit_withitem(&mut self, node: &'a WithItem) {
    self.visit_expr(node.context_expr);
    if Some(optional_vars) = node.optional_vars {
      self.visit_expr(optional_vars);
    }
  }

  fn generic_match_case(&mut self, node: &'a MatchCase) {
    self.visit_pattern(node.pattern);
    self.visit_expr(node.guard);
    self.visit_stmts(node.body);
  }

  fn generic_pattern(&mut self, node: &'a Pattern) {
    match &node.node {
      PatternKind::MatchValue { value } => self.visit_MatchValue(PatternKind::MatchValue { value }),
      PatternKind::MatchSingleton { value } => {
        self.visit_MatchSingleton(PatternKind::MatchSingleton { value })
      }
      PatternKind::MatchSequence { patterns } => {
        self.visit_MatchSequence(PatternKind::MatchSequence { patterns })
      }
      PatternKind::MatchMapping {
        keys,
        patterns,
        rest,
      } => self.visit_MatchMapping(PatternKind::MatchMapping {
        keys,
        patterns,
        rest,
      }),
      PatternKind::MatchClass {
        cls,
        patterns,
        kwd_attrs,
        kwd_patterns,
      } => self.visit_MatchClass(PatternKind::MatchClass {
        cls,
        patterns,
        kwd_attrs,
        kwd_patterns,
      }),
      PatternKind::MatchStar { name } => self.visit_MatchStar(PatternKind::MatchStar { name }),
      PatternKind::MatchAs { pattern, name } => {
        self.visit_MatchAs(PatternKind::MatchAs { pattern, name })
      }
      PatternKind::MatchOr { patterns } => self.visit_MatchOr(PatternKind::MatchOr { patterns }),
    }
  }

  fn generic_visit_MatchValue(&mut self, node: &'a PatternKind::MatchValue) {
    self.visit_expr(node.value);
  }
  fn generic_visit_MatchSingleton(&mut self, node: &'a PatternKind::MatchSingleton) {
    self.visit_Constant(node.value);
  }
  fn generic_visit_MatchSequence(&mut self, node: &'a PatternKind::MatchSequence) {
    self.visit_patterns(node.patterns);
  }
  fn generic_visit_MatchMapping(&mut self, node: &'a PatternKind::MatchMapping) {
    self.visit_exprs(&node.keys);
    self.visit_patterns(node.patterns);
  }
  fn generic_visit_MatchClass(&mut self, node: &'a PatternKind::MatchClass) {
    self.visit_expr(node.cls);
    self.visit_patterns(node.patterns);
    self.visit_patterns(node.kwd_patterns);
  }
  fn visit_MatchStar(&mut self, node: &'a PatternKind::MatchStar) {
    self.generic_visit_MatchStar(node);
  }
  fn generic_visit_MatchStar(&mut self, node: &'a PatternKind::MatchStar) {}
  fn generic_visit_MatchAs(&mut self, node: &'a PatternKind::MatchAs) {
    if Some(pattern) = node.pattern {
      self.visit_pattern(pattern);
    }
  }
  fn generic_visit_MatchOr(&mut self, node: &'a PatternKind::MatchOr) {
    self.visit_patterns(node.kwd_patterns);
  }

  // ==================
  // @TODO: Move these to macros

  fn visit_stmts(&mut self, stmts: &'a [Stmt]) {
    for stmt in body {
      self.visit_stmt(stmt);
    }
  }

  fn visit_exprs(&mut self, exprs: &'a [Expr]) {
    for expr in exprs {
      self.visit_expr(expr);
    }
  }

  fn visit_patterns(&mut self, patterns: &'a [Pattern]) {
    for pattern in patterns {
      self.visit_pattern(pattern);
    }
  }

  fn visit_comprehensions(&mut self, comprehensions: &'a [Comprehension]) {
    for comprehension in comprehensions {
      self.visit_comprehension(comprehension);
    }
  }

  fn visit_keywords(&mut self, keywords: &'a [Keyword]) {
    for keyword in keywords {
      self.visit_keyword(keyword);
    }
  }

  fn visit_stmt(&mut self, stmt: &'a Stmt) {
    match &stmt.node {
      StmtKind::FunctionDef {
        name,
        args,
        body,
        decorator_list,
        returns,
        type_comment,
      } => self.visit_FunctionDef(StmtKind::FunctionDef {
        name,
        args,
        body,
        decorator_list,
        returns,
        type_comment,
      }),
      StmtKind::AsyncFunctionDef {
        name,
        args,
        body,
        decorator_list,
        returns,
        type_comment,
      } => self.visit_AsyncFunctionDef(StmtKind::AsyncFunctionDef {
        name,
        args,
        body,
        decorator_list,
        returns,
        type_comment,
      }),
      StmtKind::ClassDef {
        name,
        bases,
        keywords,
        body,
        decorator_list,
      } => self.visit_ClassDef(StmtKind::ClassDef {
        name,
        bases,
        keywords,
        body,
        decorator_list,
      }),
      StmtKind::Return { value } => self.visit_Return(StmtKind::Return { value }),
      StmtKind::Delete { targets } => self.visit_Delete(StmtKind::Delete { targets }),
      StmtKind::Assign {
        targets,
        value,
        type_comment,
      } => self.visit_Assign(StmtKind::Assign {
        targets,
        value,
        type_comment,
      }),
      StmtKind::AugAssign { target, op, value } => {
        self.visit_AugAssign(StmtKind::AugAssign { target, op, value })
      }
      StmtKind::AnnAssign {
        target,
        annotation,
        value,
        simple,
      } => self.visit_AnnAssign(StmtKind::AnnAssign {
        target,
        annotation,
        value,
        simple,
      }),
      StmtKind::For {
        target,
        iter,
        body,
        orelse,
        type_comment,
      } => self.visit_For(StmtKind::For {
        target,
        iter,
        body,
        orelse,
        type_comment,
      }),
      StmtKind::AsyncFor {
        target,
        iter,
        body,
        orelse,
        type_comment,
      } => self.visit_AsyncFor(StmtKind::AsyncFor {
        target,
        iter,
        body,
        orelse,
        type_comment,
      }),
      StmtKind::While { test, body, orelse } => {
        self.visit_While(StmtKind::While { test, body, orelse })
      }
      StmtKind::If { test, body, orelse } => self.visit_If(StmtKind::If { test, body, orelse }),
      StmtKind::With {
        items,
        body,
        type_comment,
      } => self.visit_With(StmtKind::With {
        items,
        body,
        type_comment,
      }),
      StmtKind::AsyncWith {
        items,
        body,
        type_comment,
      } => self.visit_AsyncWith(StmtKind::AsyncWith {
        items,
        body,
        type_comment,
      }),
      StmtKind::Match { subject, cases } => self.visit_Match(StmtKind::Match { subject, cases }),
      StmtKind::Raise { exc, cause } => self.visit_Raise(StmtKind::Raise { exc, cause }),
      StmtKind::Try {
        body,
        handlers,
        orelse,
        finalbody,
      } => self.visit_Try(StmtKind::Try {
        body,
        handlers,
        orelse,
        finalbody,
      }),
      StmtKind::Assert { test, msg } => self.visit_Assert(StmtKind::Assert { test, msg }),
      StmtKind::Import { names } => self.visit_Import(StmtKind::Import { names }),
      StmtKind::ImportFrom {
        module,
        names,
        level,
      } => self.visit_ImportFrom(StmtKind::ImportFrom {
        module,
        names,
        level,
      }),
      StmtKind::Global { names } => self.visit_Global(StmtKind::Global { names }),
      StmtKind::Nonlocal { names } => self.visit_Nonlocal(StmtKind::Nonlocal { names }),
      StmtKind::Expr { value } => self.visit_Expr(StmtKind::Expr { value }),
      StmtKind::Pass => self.visit_Pass(StmtKind::Pass),
      StmtKind::Break => self.visit_Break(StmtKind::Break),
      StmtKind::Continue => self.visit_Continue(StmtKind::Continue),
    }
  }

  fn visit_expr(&mut self, expr: &'a Expr) {
    match expr.node {
      ExprKind::BoolOp { op, values } => self.visit_BoolOp(ExprKind::BoolOp { op, values }),
      ExprKind::NamedExpr { target, value } => {
        self.visit_NamedExpr(ExprKind::NamedExpr { target, value })
      }
      ExprKind::BinOp { left, op, right } => self.visit_BinOp(ExprKind::BinOp { left, op, right }),
      ExprKind::UnaryOp { op, operand } => self.visit_UnaryOp(ExprKind::UnaryOp { op, operand }),
      ExprKind::Lambda { args, body } => self.visit_Lambda(ExprKind::Lambda { args, body }),
      ExprKind::IfExp { test, body, orelse } => {
        self.visit_IfExp(ExprKind::IfExp { test, body, orelse })
      }
      ExprKind::Dict { keys, values } => self.visit_Dict(ExprKind::Dict { keys, values }),
      ExprKind::Set { elts } => self.visit_Set(ExprKind::Set { elts }),
      ExprKind::ListComp { elt, generators } => {
        self.visit_ListComp(ExprKind::ListComp { elt, generators })
      }
      ExprKind::SetComp { elt, generators } => {
        self.visit_SetComp(ExprKind::SetComp { elt, generators })
      }
      ExprKind::DictComp {
        key,
        value,
        generators,
      } => self.visit_DictComp(ExprKind::DictComp {
        key,
        value,
        generators,
      }),
      ExprKind::GeneratorExp { elt, generators } => {
        self.visit_GeneratorExp(ExprKind::GeneratorExp { elt, generators })
      }
      ExprKind::Await { value } => self.visit_Await(ExprKind::Await { value }),
      ExprKind::Yield { value } => self.visit_Yield(ExprKind::Yield { value }),
      ExprKind::YieldFrom { value } => self.visit_YieldFrom(ExprKind::YieldFrom { value }),
      ExprKind::Compare {
        left,
        ops,
        comparators,
      } => self.visit_Compare(ExprKind::Compare {
        left,
        ops,
        comparators,
      }),
      ExprKind::Call {
        func,
        args,
        keywords,
      } => self.visit_Call(ExprKind::Call {
        func,
        args,
        keywords,
      }),
      ExprKind::FormattedValue {
        value,
        conversion,
        format_spec,
      } => self.visit_FormattedValue(ExprKind::FormattedValue {
        value,
        conversion,
        format_spec,
      }),
      ExprKind::JoinedStr { values } => self.visit_JoinedStr(ExprKind::JoinedStr { values }),
      ExprKind::Constant { value, kind } => self.visit_Constant(ExprKind::Constant { value, kind }),
      ExprKind::Attribute { value, attr, ctx } => {
        self.visit_Attribute(ExprKind::Attribute { value, attr, ctx })
      }
      ExprKind::Subscript { value, slice, ctx } => {
        self.visit_Subscript(ExprKind::Subscript { value, slice, ctx })
      }
      ExprKind::Starred { value, ctx } => self.visit_Starred(ExprKind::Starred { value, ctx }),
      ExprKind::Name { id, ctx } => self.visit_Name(ExprKind::Name { id, ctx }),
      ExprKind::List { elts, ctx } => self.visit_List(ExprKind::List { elts, ctx }),
      ExprKind::Tuple { elts, ctx } => self.visit_Tuple(ExprKind::Tuple { elts, ctx }),
      ExprKind::Slice { lower, upper, step } => {
        self.visit_Slice(ExprKind::Slice { lower, upper, step })
      }
    }
  }
}
