// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::iter::{once, Once};
use std::path::{Path, PathBuf};

use fnv::{FnvBuildHasher, FnvHashMap as HashMap, FnvHashSet as HashSet};
use itertools::Either;
use serde_derive::{Deserialize, Serialize};
use tree_sitter::{Node, Parser};

use crate::code;
use protos::gen::pants::cache::{
    javascript_inference_metadata::ImportPattern, JavascriptInferenceMetadata,
};

use crate::javascript::import_pattern::{imports_from_patterns, Import};
use crate::javascript::util::normalize_path;

mod import_pattern;
mod util;

include!(concat!(env!("OUT_DIR"), "/javascript/constants.rs"));
include!(concat!(env!("OUT_DIR"), "/javascript/visitor.rs"));
include!(concat!(env!("OUT_DIR"), "/javascript_impl_hash.rs"));

#[derive(Debug, Serialize, Deserialize)]
pub struct ParsedJavascriptDependencies {
    pub imports: HashMap<String, JavascriptImportInfo>,
}

#[derive(Debug, PartialEq, Serialize, Deserialize)]
pub struct JavascriptImportInfo {
    pub file_imports: HashSet<String>,
    pub package_imports: HashSet<String>,
}

impl JavascriptImportInfo {
    fn from_sets(file_imports: HashSet<String>, package_imports: HashSet<String>) -> Self {
        JavascriptImportInfo {
            file_imports,
            package_imports,
        }
    }
    
    #[cfg(test)]
    fn new<F: AsRef<str>, T: AsRef<str>>(
        file_imports: impl IntoIterator<Item = F>,
        package_imports: impl IntoIterator<Item = T>,
    ) -> Self {
        JavascriptImportInfo::from_sets(
            file_imports
                .into_iter()
                .map(|s| s.as_ref().to_string())
                .collect(),
            package_imports
                .into_iter()
                .map(|s| s.as_ref().to_string())
                .collect(),
        )
    }
}

fn patterns_as_lookup(patterns: Vec<ImportPattern>) -> HashMap<String, Vec<String>> {
    patterns
        .into_iter()
        .map(|pattern| (pattern.pattern, pattern.replacements))
        .collect()
}

fn placed_at_root(package_root: &str, string: &str) -> bool {
    !package_root.is_empty() && string.starts_with(package_root)
}

fn is_relative_specifier(string: &str) -> bool {
    ['.', '/'].into_iter().any(|p| string.starts_with(p))
}

fn match_and_extend_with_config_candidates(
    string: String,
    paths: &HashMap<String, Vec<String>>,
    config_root: Option<&str>,
) -> Either<Once<Import>, impl Iterator<Item = Import>> {
    if let Some(imports) = config_root.map(|root| imports_from_patterns(root, paths, &string)) {
        Either::Right(imports.into_iter().chain(once(Import::UnMatched(string))))
    } else {
        Either::Left(once(Import::UnMatched(string)))
    }
}

pub fn get_dependencies(
    contents: &str,
    filepath: PathBuf,
    metadata: JavascriptInferenceMetadata,
) -> Result<ParsedJavascriptDependencies, String> {
    let import_patterns = patterns_as_lookup(metadata.import_patterns);
    let paths = patterns_as_lookup(metadata.paths);

    let mut collector = ImportCollector::new(contents);
    collector.collect();
    let mut imports =
        HashMap::with_capacity_and_hasher(collector.imports.len(), FnvBuildHasher::default());
    for import in collector.imports {
        let (relative_files, packages) =
            imports_from_patterns(&metadata.package_root, &import_patterns, &import)
                .into_iter()
                .flat_map(|import| match import {
                    Import::UnMatched(string) if !is_relative_specifier(&string) => {
                        match_and_extend_with_config_candidates(
                            string,
                            &paths,
                            metadata.config_root.as_deref(),
                        )
                    }
                    matched => Either::Left(once(matched)),
                })
                .flatten()
                .partition(|import| {
                    is_relative_specifier(import) || placed_at_root(&metadata.package_root, import)
                });
        imports.insert(
            import,
            JavascriptImportInfo::from_sets(
                normalize_from_path(&metadata.package_root, &filepath, relative_files),
                packages,
            ),
        );
    }

    Ok(ParsedJavascriptDependencies { imports })
}

fn normalize_from_path(
    root: &str,
    filepath: &Path,
    file_imports: HashSet<String>,
) -> HashSet<String> {
    let directory = filepath.parent().unwrap_or(Path::new(""));
    file_imports
        .into_iter()
        .map(|string| {
            let path = Path::new(&string);
            if path.has_root() {
                string
            } else if placed_at_root(root, &string) {
                normalize_path(path).map_or(string, |path| path.to_string_lossy().to_string())
            } else {
                normalize_path(&directory.join(path))
                    .map_or(string, |path| path.to_string_lossy().to_string())
            }
        })
        .collect()
}

struct ImportCollector<'a> {
    pub imports: Vec<String>,
    code: &'a str,
}

impl ImportCollector<'_> {
    pub fn new(code: &'_ str) -> ImportCollector<'_> {
        ImportCollector {
            imports: Vec::new(),
            code,
        }
    }

    pub fn collect(&mut self) {
        let mut parser = Parser::new();
        parser
            .set_language(tree_sitter_javascript::language())
            .expect("Error loading Javascript grammar");
        let parsed = parser.parse(self.code, None);
        let tree = parsed.unwrap();
        let mut cursor = tree.walk();

        self.walk(&mut cursor);
    }

    fn code_at(&self, range: tree_sitter::Range) -> &str {
        code::at_range(self.code, range)
    }

    fn is_pragma_ignored(&self, node: Node) -> bool {
        fn comment_after_semicolon(node: Node) -> Option<Node> {
            node.next_named_sibling()
                .filter(|comment| comment.kind_id() == KindID::COMMENT)
        }
        fn comment_after_no_semicolon(node: Node) -> Option<Node> {
            node.children(&mut node.walk())
                .find(|node| node.kind_id() == KindID::COMMENT)
        }
        let contains_pragma = |node: Node, comment: Node| -> bool {
            let comment_range = comment.range();
            node.range().end_point.row == comment_range.start_point.row
                && self
                    .code_at(comment_range)
                    .contains("// pants: no-infer-dep")
        };
        comment_after_semicolon(node)
            .or_else(|| comment_after_no_semicolon(node))
            .map_or(false, |comment| contains_pragma(node, comment))
    }

    fn insert_import(&mut self, import_string: Option<Node>) {
        if let Some(import_string) = import_string {
            let import_string = self.code_at(import_string.range());
            self.imports
                .push(import_string.strip_first_last().to_string())
        }
    }

    fn propagate_pragma(&self, node: Node) -> ChildBehavior {
        if !self.is_pragma_ignored(node) {
            return ChildBehavior::Visit;
        }
        ChildBehavior::Ignore
    }
}

impl Visitor for ImportCollector<'_> {
    fn visit_import_statement(&mut self, node: Node) -> ChildBehavior {
        if !self.is_pragma_ignored(node) {
            self.insert_import(node.child_by_field_name("source"));
        }
        ChildBehavior::Ignore
    }

    fn visit_export_statement(&mut self, node: Node) -> ChildBehavior {
        if !self.is_pragma_ignored(node) {
            self.insert_import(node.child_by_field_name("source"));
        }

        ChildBehavior::Ignore
    }

    fn visit_expression_statement(&mut self, node: Node) -> ChildBehavior {
        if node.children(&mut node.walk()).any(|child| {
            let id = child.kind_id();
            KindID::CALL_EXPRESSION.contains(&id) || id == KindID::AWAIT_EXPRESSION
        }) {
            return self.propagate_pragma(node);
        }
        ChildBehavior::Ignore
    }

    fn visit_lexical_declaration(&mut self, node: Node) -> ChildBehavior {
        self.propagate_pragma(node)
    }

    fn visit_call_expression(&mut self, node: Node) -> ChildBehavior {
        if let (Some(function), Some(args)) = (node.named_child(0), node.named_child(1)) {
            if let "require" | "import" = self.code_at(function.range()) {
                for arg in args.children(&mut args.walk()) {
                    if arg.kind_id() == KindID::STRING {
                        self.insert_import(Some(arg))
                    }
                }
            }
        }
        ChildBehavior::Ignore
    }
}

trait StripFirstLast {
    fn strip_first_last(&self) -> &Self;
}

impl StripFirstLast for str {
    fn strip_first_last(&self) -> &Self {
        let mut chars = self.chars();
        chars.next();
        chars.next_back();
        chars.as_str()
    }
}

#[cfg(test)]
mod tests;
