// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::borrow::Cow;
use std::path::PathBuf;

use fnv::{FnvHashMap as HashMap, FnvHashSet as HashSet};
use serde_derive::{Deserialize, Serialize};
use tree_sitter::Parser;

use crate::code;

include!(concat!(env!("OUT_DIR"), "/python/constants.rs"));
include!(concat!(env!("OUT_DIR"), "/python/visitor.rs"));
include!(concat!(env!("OUT_DIR"), "/python_impl_hash.rs"));

#[derive(Serialize, Deserialize)]
pub struct ParsedPythonDependencies {
    pub imports: HashMap<String, (u64, bool)>,
    pub string_candidates: HashMap<String, u64>,
    pub explicit_dependencies: HashMap<String, u64>,
}

pub fn get_dependencies(
    contents: &str,
    filepath: PathBuf,
) -> Result<ParsedPythonDependencies, String> {
    let mut collector = ImportCollector::new(contents);
    collector.collect();

    let mut import_map = collector.import_map;

    // NB: the import collector doesn't do anything special for relative imports, we need to fix
    // those up.
    let keys_to_replace: HashSet<_> = import_map
        .keys()
        .filter(|key| key.starts_with('.'))
        .cloned()
        .collect();
    let parent_path = filepath
        .parent()
        .expect("Expected a filepath that was non-root");
    let path_parts: Vec<&str> = parent_path
        .iter()
        .map(|p| {
            p.to_str()
                .expect("Expected UTF-8-compatible filepath parts")
        })
        .collect();
    for key in keys_to_replace {
        let nonrelative = key.trim_start_matches('.');
        let level = key.len() - nonrelative.len();
        if level > path_parts.len() {
            // Don't mess with the key, let Pants error with the original string
            continue;
        }

        let mut new_key_parts = path_parts[0..((path_parts.len() - level) + 1)].to_vec();
        if !nonrelative.is_empty() {
            // an import like `from .. import *` can end up with key == '..', and hence nonrelative == "";
            // the result should just be the raw parent traversal, without a suffix part
            new_key_parts.push(nonrelative);
        }

        let old_value = import_map.remove(&key).unwrap();
        import_map.insert(new_key_parts.join("."), old_value);
    }

    Ok(ParsedPythonDependencies {
        imports: import_map,
        string_candidates: collector.string_candidates,
        explicit_dependencies: collector.explicit_dependencies,
    })
}

struct ImportCollector<'a> {
    pub import_map: HashMap<String, (u64, bool)>,
    pub string_candidates: HashMap<String, u64>,
    pub explicit_dependencies: HashMap<String, u64>,
    code: &'a str,
    weaken_imports: bool,
}

/// Input to `insert_import` to specify the base of an import statement.
enum BaseNode<'a> {
    Node(tree_sitter::Node<'a>),
    StringNode(String, tree_sitter::Node<'a>),
}

impl ImportCollector<'_> {
    pub fn new(code: &'_ str) -> ImportCollector<'_> {
        ImportCollector {
            import_map: HashMap::default(),
            string_candidates: HashMap::default(),
            explicit_dependencies: HashMap::default(),
            code,
            weaken_imports: false,
        }
    }

    pub fn collect(&mut self) {
        let mut parser = Parser::new();
        parser
            .set_language(&tree_sitter_python::LANGUAGE.into())
            .expect("Error loading Python grammar");
        let parsed = parser.parse(self.code, None);
        let tree = parsed.unwrap();
        let mut cursor = tree.walk();

        self.walk(&mut cursor);
    }

    fn code_at(&self, range: tree_sitter::Range) -> &str {
        code::at_range(self.code, range)
    }

    /// Extract an optional "import name" string from a string-related `tree_sitter::Node`. The string is
    /// expected to analyze statically as an import name and so `extract_string` ignores any strings
    /// containing escape sequences as well as any use of f-strings with interpolations.
    fn extract_string(&self, node: tree_sitter::Node) -> Option<String> {
        match node.kind_id() {
            KindID::STRING => {
                if node.child_count() != 3 {
                    // String literals are expected to have exactly three children consisting of `string_start`, `string_content`,
                    // and `string_end`.  If there are more children, then it means that `interpolation` nodes are present, which
                    // means that the string is an f-string and not an import name that may be analyzed statically.
                    return None;
                }

                let content_node = node.child(1)?;
                if content_node.kind_id() != KindID::STRING_CONTENT
                    || content_node.child_count() > 0
                {
                    // The `string_content` node is expected to have no children if the string is a simple string literal.
                    // If there are children, then it means that the string contains escape sequences and is not an import name
                    // (either an `escape_sequence` or `escape_interpolation` node).
                    return None;
                }

                let content = code::at_range(self.code, content_node.range());
                Some(content.to_string())
            }
            KindID::CONCATENATED_STRING => {
                let substrings: Vec<Option<String>> = node
                    .children(&mut node.walk())
                    .filter(|n| n.kind_id() != KindID::COMMENT)
                    .map(|n| self.extract_string(n))
                    .collect();
                if substrings.iter().any(|s| s.is_none()) {
                    return None;
                }
                let substrings: Vec<String> = substrings.into_iter().flatten().collect();
                Some(substrings.join(""))
            }
            _ => None,
        }
    }

    fn is_pragma_ignored_at_row(&self, node: tree_sitter::Node, end_row: usize) -> bool {
        let node_range = node.range();
        if node.kind_id() == KindID::COMMENT
            && end_row == node_range.start_point.row
            && self.code_at(node_range).contains("# pants: no-infer-dep")
        {
            return true;
        }
        false
    }

    fn is_pragma_ignored(&self, node: tree_sitter::Node) -> bool {
        if let Some(sibling) = node.next_named_sibling() {
            return self.is_pragma_ignored_at_row(sibling, node.range().end_point.row);
        }
        false
    }

    fn is_pragma_ignored_recursive(&self, node: tree_sitter::Node) -> bool {
        let node_end_point = node.range().end_point;
        if let Some(sibling) = node.next_named_sibling()
            && self.is_pragma_ignored_at_row(sibling, node_end_point.row)
        {
            return true;
        }

        let mut current = node;
        loop {
            if let Some(parent) = current.parent() {
                if let Some(sibling) = parent.next_named_sibling()
                    && self.is_pragma_ignored_at_row(sibling, node_end_point.row)
                {
                    return true;
                }
                current = parent;
                continue;
            }
            // At the root / no more parents.
            break;
        }

        false
    }

    fn unnest_alias(node: tree_sitter::Node) -> tree_sitter::Node {
        match node.kind_id() {
            KindID::ALIASED_IMPORT => node
                .named_child(0)
                .expect("aliased imports must have a child"),
            _ => node,
        }
    }

    /// Handle different styles of references to modules/imports
    ///
    /// ```python
    /// import $base
    /// "$base"  # string import
    /// from $base import *  # (the * node is passed as `specific` too)
    /// from $base import $specific
    /// ```
    fn insert_import(&mut self, base: BaseNode, specific: Option<tree_sitter::Node>) {
        // the specifically-imported item takes precedence over the base name for ignoring and lines
        // etc.
        let most_specific = match base {
            BaseNode::Node(n) => specific.unwrap_or(n),
            BaseNode::StringNode(_, n) => specific.unwrap_or(n),
        };

        if self.is_pragma_ignored(most_specific) {
            return;
        }

        let base_ref = match base {
            BaseNode::Node(node) => {
                let node = Self::unnest_alias(node);
                Cow::Borrowed(self.code_at(node.range()))
            }
            BaseNode::StringNode(s, _) => Cow::Owned(s),
        };

        // * and errors are the same as not having an specific import
        let specific = specific
            .map(ImportCollector::unnest_alias)
            .filter(|n| !matches!(n.kind_id(), KindID::WILDCARD_IMPORT | KindID::ERROR));

        let full_name = match specific {
            Some(specific) => {
                let specific_ref = Cow::Borrowed(self.code_at(specific.range()));
                // `from ... import a` => `...a` should concat base_ref and specific_ref directly, but `from
                // x import a` => `x.a` needs to insert a . between them
                let joiner = if base_ref.ends_with('.') { "" } else { "." };
                [base_ref, specific_ref].join(joiner)
            }
            None => base_ref.to_string(),
        };

        let line0 = most_specific.range().start_point.row;

        self.import_map
            .entry(full_name)
            .and_modify(|v| *v = (v.0, v.1 && self.weaken_imports))
            .or_insert(((line0 as u64) + 1, self.weaken_imports));
    }

    fn handle_string_candidate(&mut self, node: tree_sitter::Node) {
        if let Some(text) = self.extract_string(node)
            && !text.contains(|c: char| c.is_ascii_whitespace() || c == '\\')
            && !self.is_pragma_ignored_recursive(node)
        {
            self.string_candidates
                .insert(text, (node.range().start_point.row + 1) as u64);
        }
    }
}

const _INFER_DEP_PREFIX: &str = "# pants: infer-dep(";
const _INFER_DEP_SUFFIX: &str = ")";

// NB: https://tree-sitter.github.io/tree-sitter/7-playground.html is very helpful
impl Visitor for ImportCollector<'_> {
    fn visit_comment(&mut self, node: tree_sitter::Node) -> ChildBehavior {
        let comment_text = self.code_at(node.range()).trim();
        if comment_text.starts_with(_INFER_DEP_PREFIX) && comment_text.ends_with(_INFER_DEP_SUFFIX)
        {
            // Prefix and suffix are ASCII so the subslice will be on character boundaries.
            let dep_text = comment_text
                [_INFER_DEP_PREFIX.len()..comment_text.len() - _INFER_DEP_SUFFIX.len()]
                .to_string();
            self.explicit_dependencies
                .insert(dep_text, (node.range().start_point.row + 1) as u64);
        }
        ChildBehavior::Ignore
    }

    fn visit_import_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior {
        if !self.is_pragma_ignored(node) {
            self.insert_import(BaseNode::Node(node.named_child(0).unwrap()), None);
        }
        ChildBehavior::Ignore
    }

    fn visit_import_from_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior {
        if !self.is_pragma_ignored(node) {
            // the grammar is something like `from $module_name import $($name),* | '*'`, where $... is a field
            // name.
            let module_name = node
                .child_by_field_name("module_name")
                .expect("`from ... import ...` must have module_name");

            let mut any_inserted = false;
            for child in node.children_by_field_name("name", &mut node.walk()) {
                self.insert_import(BaseNode::Node(module_name), Some(child));
                any_inserted = true;
            }

            if !any_inserted {
                // There's no names (i.e. it's probably not `from ... import some, names`), let's look for
                // the * in a wildcard import. (It doesn't have a field name, so we have to search for it
                // manually.)
                for child in node.children(&mut node.walk()) {
                    if child.kind_id() == KindID::WILDCARD_IMPORT {
                        self.insert_import(BaseNode::Node(module_name), Some(child));
                        any_inserted = true
                    }
                }
            }

            if !any_inserted {
                // Still nothing inserted, which means something has probably gone wrong and/or we haven't
                // understood the syntax tree! We're working on a definite import statement, so silently
                // doing nothing with it is likely to be wrong. Let's insert the import node itself and let
                // that be surfaced as an dep-inference failure.
                self.insert_import(BaseNode::Node(node), None)
            }
        }
        ChildBehavior::Ignore
    }

    fn visit_try_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior {
        let mut should_weaken = false;
        let mut cursor = node.walk();
        let children: Vec<_> = node.named_children(&mut cursor).collect();
        for child in children.iter() {
            if child.kind_id() == KindID::EXCEPT_CLAUSE {
                // N.B. Python allows any arbitrary expression as an except handler.
                // We only parse identifiers, or (Set/Tuple/List)-of-identifier expressions.
                let except_expr = child.named_child(0).unwrap();
                should_weaken = match except_expr.kind_id() {
                    KindID::IDENTIFIER => self.code_at(except_expr.range()) == "ImportError",
                    KindID::SET | KindID::LIST | KindID::TUPLE => except_expr
                        .named_children(&mut except_expr.walk())
                        .any(|expr| {
                            expr.kind_id() == KindID::IDENTIFIER
                                && self.code_at(expr.range()) == "ImportError"
                        }),
                    _ => false,
                };
                if should_weaken {
                    break;
                }
            }
        }

        for child in children.iter() {
            let previous_weaken = self.weaken_imports;
            if KindID::BLOCK.contains(&child.kind_id()) {
                self.weaken_imports = should_weaken;
            }
            self.walk(&mut child.walk());
            self.weaken_imports = previous_weaken;
        }
        ChildBehavior::Ignore
    }

    fn visit_with_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior {
        let with_clause = node.named_child(0).unwrap();

        let are_suppressing_importerror = with_clause
            .named_children(&mut with_clause.walk())
            .any(|x| self.suppressing_importerror(x));

        // remember to visit the withitems themselves
        // for ex detecting imports in `with open("/foo/bar") as f`
        for child in with_clause.named_children(&mut with_clause.walk()) {
            self.walk(&mut child.walk());
        }

        let body_node = node.child_by_field_name("body").unwrap();
        let body: Vec<_> = body_node.named_children(&mut body_node.walk()).collect();

        if are_suppressing_importerror {
            let previous_weaken = self.weaken_imports;
            self.weaken_imports = true;

            for child in body {
                self.walk(&mut child.walk());
            }
            self.weaken_imports = previous_weaken;
        } else {
            for child in body {
                self.walk(&mut child.walk());
            }
        }

        ChildBehavior::Ignore
    }

    fn visit_call(&mut self, node: tree_sitter::Node) -> ChildBehavior {
        let funcname = node.named_child(0).unwrap();
        if self.code_at(funcname.range()) != "__import__" {
            return ChildBehavior::Visit;
        }

        let args = node.named_child(1).unwrap();
        if let Some(arg) = args.named_child(0)
            && let Some(content) = self.extract_string(arg)
            && !self.is_pragma_ignored(node.parent().unwrap())
        {
            self.insert_import(BaseNode::StringNode(content, arg), None);
        }

        // Do not descend below the `__import__` call statement.
        ChildBehavior::Ignore
    }

    fn visit_concatenated_string(&mut self, node: tree_sitter::Node) -> ChildBehavior {
        self.handle_string_candidate(node);
        ChildBehavior::Ignore
    }

    fn visit_string(&mut self, node: tree_sitter::Node) -> ChildBehavior {
        self.handle_string_candidate(node);
        ChildBehavior::Ignore
    }
}

impl ImportCollector<'_> {
    fn suppressing_importerror(&mut self, with_node: tree_sitter::Node) -> bool {
        if with_node.kind_id() == KindID::WITH_ITEM {
            let node = with_node.child_by_field_name("value").unwrap(); // synthetic

            let call_maybe_of_suppress = if node.kind_id() == KindID::CALL {
                Some(node) // if we have a call directly `with suppress(ImportError):`
            } else if KindID::AS_PATTERN.contains(&node.kind_id()) {
                node.named_child(0).and_then(|n| match n.kind_id() {
                    KindID::CALL => Some(n),
                    _ => None,
                }) // if we have a call with an `as` item `with suppress(ImportError) as e:`
            } else {
                None
            };

            if call_maybe_of_suppress.is_none() {
                return false;
            }

            let function_name_expr = call_maybe_of_suppress
                .unwrap()
                .child_by_field_name("function")
                .unwrap();
            let is_supress = match function_name_expr.kind_id() {
                KindID::ATTRIBUTE => function_name_expr
                    .child_by_field_name("attribute")
                    .map(|identifier| self.code_at(identifier.range()) == "suppress")
                    .unwrap_or(false),
                KindID::IDENTIFIER => self.code_at(function_name_expr.range()) == "suppress",
                _ => false,
            };
            if !is_supress {
                return false;
            }
            let cur = &mut node.walk();

            let has_importerror = call_maybe_of_suppress
                .unwrap()
                .child_by_field_name("arguments")
                .map(|x| {
                    x.named_children(cur)
                        .any(|arg| self.code_at(arg.range()) == "ImportError")
                })
                .unwrap_or(false);
            is_supress && has_importerror
        } else {
            false
        }
    }
}

#[cfg(test)]
mod tests;
