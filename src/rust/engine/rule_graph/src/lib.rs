// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
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

mod builder;
mod rules;

use std::io;

use deepsize::DeepSizeOf;
use fnv::{FnvHashMap as HashMap, FnvHashSet as HashSet};
use indexmap::IndexSet;
use internment::Intern;

pub use crate::builder::Builder;
pub use crate::rules::{
    DependencyKey, DisplayForGraph, DisplayForGraphArgs, ParamTypes, Query, Rule, TypeId,
};

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
struct UnreachableError<R: Rule> {
    rule: R,
    diagnostic: Diagnostic<R>,
}

impl<R: Rule> UnreachableError<R> {
    #[allow(dead_code)]
    fn new(rule: R) -> UnreachableError<R> {
        UnreachableError {
      rule,
      diagnostic: Diagnostic {
        params: ParamTypes::default(),
        reason: "Was not reachable, either because no rules could produce the params or because it was shadowed by another @rule.".to_string(),
        details: vec![],
      },
    }
    }
}

#[derive(DeepSizeOf, Eq, Hash, PartialEq, Clone, Debug)]
pub enum EntryWithDeps<R: Rule> {
    Root(RootEntry<R>),
    Rule(RuleEntry<R>),
    Reentry(Reentry<R::TypeId>),
}

impl<R: Rule> EntryWithDeps<R> {
    pub fn rule(&self) -> Option<R> {
        match self {
            EntryWithDeps::Rule(RuleEntry { rule, .. }) => Some(rule.clone()),
            EntryWithDeps::Root(_) | EntryWithDeps::Reentry(_) => None,
        }
    }

    pub fn params(&self) -> &ParamTypes<R::TypeId> {
        match self {
            EntryWithDeps::Rule(ref ie) => &ie.params,
            EntryWithDeps::Root(ref re) => &re.0.params,
            EntryWithDeps::Reentry(ref re) => &re.params,
        }
    }
}

#[derive(DeepSizeOf, Eq, Hash, PartialEq, Clone, Debug)]
pub enum Entry<R: Rule> {
    Param(R::TypeId),
    WithDeps(Intern<EntryWithDeps<R>>),
}

#[derive(DeepSizeOf, Eq, Hash, PartialEq, Clone, Debug)]
pub struct RootEntry<R: Rule>(Query<R::TypeId>);

#[derive(DeepSizeOf, Eq, Hash, PartialEq, Clone, Debug)]
pub struct Reentry<T: TypeId> {
    params: ParamTypes<T>,
    pub query: Query<T>,
}

#[derive(DeepSizeOf, Eq, Hash, PartialEq, Clone, Debug)]
pub struct RuleEntry<R: Rule> {
    params: ParamTypes<R::TypeId>,
    rule: R,
}

impl<R: Rule> RuleEntry<R> {
    pub fn rule(&self) -> &R {
        &self.rule
    }
}

type RuleDependencyEdges<R> = HashMap<Intern<EntryWithDeps<R>>, RuleEdges<R>>;

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
struct Diagnostic<R: Rule> {
    params: ParamTypes<R::TypeId>,
    reason: String,
    details: Vec<(Entry<R>, Option<&'static str>)>,
}

///
/// A graph mapping rules to their dependencies.
///
#[derive(Debug)]
pub struct RuleGraph<R: Rule> {
    queries: Vec<Query<R::TypeId>>,
    rule_dependency_edges: RuleDependencyEdges<R>,
    unreachable_rules: Vec<UnreachableError<R>>,
}

// TODO: We can't derive this due to https://github.com/rust-lang/rust/issues/26925, which
// unnecessarily requires `Rule: Default`.
impl<R: Rule> Default for RuleGraph<R> {
    fn default() -> Self {
        RuleGraph {
            queries: Vec::default(),
            rule_dependency_edges: RuleDependencyEdges::default(),
            unreachable_rules: Vec::default(),
        }
    }
}

fn params_str<T: TypeId>(params: &ParamTypes<T>) -> String {
    T::display(params.iter().cloned())
}

pub fn entry_str<R: Rule>(entry: &Entry<R>) -> String {
    entry.fmt_for_graph(DisplayForGraphArgs { multiline: false })
}

#[derive(Debug, Clone, PartialOrd, Ord, PartialEq, Eq)]
pub struct GraphVizEntryWithAttrs {
    entry_str: String,
    attrs_str: Option<String>,
}

pub enum Palette {
    Olive,
    Gray,
    Orange,
    Blue,
}

impl Palette {
    // https://c.eev.ee/kouyou/ is wonderful for selecting lovely color juxtapositions across multiple
    // different color axes.
    fn color_string(&self) -> String {
        // These color values are all in HSV. See https://www.graphviz.org/doc/info/colors.html for
        // other methods of specifying
        // colors. https://renenyffenegger.ch/notes/tools/Graphviz/attributes/_color/index may also be
        // useful.
        match self {
            Self::Olive => "0.2214,0.7179,0.8528".to_string(),
            Self::Gray => "0.576,0,0.6242".to_string(),
            Self::Orange => "0.08,0.5,0.976".to_string(),
            Self::Blue => "0.5,1,0.9".to_string(),
        }
    }
}

impl DisplayForGraph for Palette {
    fn fmt_for_graph(&self, _: DisplayForGraphArgs) -> String {
        format!("[color=\"{}\",style=filled]", self.color_string())
    }
}

impl<R: Rule> DisplayForGraph for Entry<R> {
    fn fmt_for_graph(&self, display_args: DisplayForGraphArgs) -> String {
        match self {
            Entry::WithDeps(e) => e.fmt_for_graph(display_args),
            Entry::Param(type_id) => format!("Param({type_id})"),
        }
    }
}

impl<R: Rule> DisplayForGraph for EntryWithDeps<R> {
    fn fmt_for_graph(&self, display_args: DisplayForGraphArgs) -> String {
        match self {
            &EntryWithDeps::Rule(RuleEntry {
                ref rule,
                ref params,
            }) => format!(
                "{}{}for {}",
                rule.fmt_for_graph(display_args),
                display_args.line_separator(),
                params_str(params)
            ),
            EntryWithDeps::Root(root) => format!(
                "Query({}){}for {}",
                root.0.product,
                display_args.line_separator(),
                params_str(&root.0.params)
            ),
            EntryWithDeps::Reentry(reentry) => format!(
                "Reentry({}){}for {}",
                reentry.query.product,
                display_args.line_separator(),
                params_str(&reentry.params)
            ),
        }
    }
}

///
/// Apply coloration to several nodes.
///
pub fn visualize_entry<R: Rule>(
    entry: &Entry<R>,
    display_args: DisplayForGraphArgs,
) -> GraphVizEntryWithAttrs {
    let entry_str = entry.fmt_for_graph(display_args);
    let attrs_str = match entry {
        Entry::WithDeps(e) => {
            // Color "singleton" entries (with no params)!
            if e.params().is_empty() {
                Some(Palette::Olive.fmt_for_graph(display_args))
            } else {
                // Color "intrinsic" entries (provided by the rust codebase)!
                e.rule()
                    .and_then(|r| r.color())
                    .map(|color| color.fmt_for_graph(display_args))
            }
        }
        &Entry::Param(_) => {
            // Color "Param"s.
            Some(Palette::Orange.fmt_for_graph(display_args))
        }
    };
    GraphVizEntryWithAttrs {
        entry_str,
        attrs_str,
    }
}

fn entry_with_deps_str<R: Rule>(entry: &EntryWithDeps<R>) -> String {
    entry.fmt_for_graph(DisplayForGraphArgs { multiline: false })
}

impl<R: Rule> RuleGraph<R> {
    pub fn new(
        rules: IndexSet<R>,
        queries: IndexSet<Query<R::TypeId>>,
    ) -> Result<RuleGraph<R>, String> {
        Builder::new(rules, queries).graph()
    }

    pub fn find_root_edges<I: IntoIterator<Item = R::TypeId>>(
        &self,
        param_inputs: I,
        product: R::TypeId,
    ) -> Result<RuleEdges<R>, String> {
        let (_, edges) = self.find_root(param_inputs, product)?;
        Ok(edges)
    }

    ///
    /// Create a copy of this RuleGraph filtered to only the subgraph below the root matched by the
    /// given product and params.
    ///
    pub fn subgraph<I: IntoIterator<Item = R::TypeId>>(
        &self,
        param_inputs: I,
        product: R::TypeId,
    ) -> Result<RuleGraph<R>, String> {
        let (root, _) = self.find_root(param_inputs, product)?;

        // Walk the graph, starting from root entries.
        let mut entry_stack: Vec<_> = vec![root];
        let mut reachable = HashMap::default();
        while let Some(entry) = entry_stack.pop() {
            if reachable.contains_key(&entry) {
                continue;
            }

            if let Some(edges) = self.rule_dependency_edges.get(&entry) {
                reachable.insert(entry, edges.clone());

                entry_stack.extend(edges.all_dependencies().filter_map(|e| match e.as_ref() {
                    Entry::WithDeps(e) => Some(e),
                    _ => None,
                }));
            } else {
                return Err(format!("Unknown entry in RuleGraph: {entry:?}"));
            }
        }

        Ok(RuleGraph {
            queries: self.queries.clone(),
            rule_dependency_edges: reachable,
            unreachable_rules: Vec::default(),
        })
    }

    ///
    /// Returns all types consumed by rules within this RuleGraph.
    ///
    pub fn consumed_types(&self) -> HashSet<R::TypeId> {
        self.rule_dependency_edges
            .iter()
            .flat_map(|(entry, edges)| {
                entry
                    .params()
                    .iter()
                    .cloned()
                    .chain(edges.dependencies.keys().map(|k| k.product()))
            })
            .collect()
    }

    ///
    /// Find the entrypoint in this RuleGraph for the given product and params.
    ///
    pub fn find_root<I: IntoIterator<Item = R::TypeId>>(
        &self,
        param_inputs: I,
        product: R::TypeId,
    ) -> Result<(Intern<EntryWithDeps<R>>, RuleEdges<R>), String> {
        let params: ParamTypes<_> = param_inputs.into_iter().collect();

        // Attempt to find an exact match.
        let maybe_root = Intern::new(EntryWithDeps::Root(RootEntry(Query {
            product,
            params: params.clone(),
        })));
        if let Some(edges) = self.rule_dependency_edges.get(&maybe_root) {
            return Ok((maybe_root, edges.clone()));
        }

        // Otherwise, scan for partial/subset matches.
        // TODO: Is it worth indexing this by product type?
        let subset_matches = self
            .rule_dependency_edges
            .iter()
            .filter_map(|(entry, edges)| match entry.as_ref() {
                EntryWithDeps::Root(ref root_entry)
                    if root_entry.0.product == product
                        && root_entry.0.params.is_subset(&params) =>
                {
                    Some((entry, edges))
                }
                _ => None,
            })
            .collect::<Vec<_>>();

        match subset_matches.len() {
            1 => {
                let (root_entry, edges) = subset_matches[0];
                Ok((*root_entry, edges.clone()))
            }
            0 => {
                // The Params were all registered as RootRules, but the combination wasn't legal.
                let mut suggestions: Vec<_> = self
                    .rule_dependency_edges
                    .keys()
                    .filter_map(|entry| match entry.as_ref() {
                        EntryWithDeps::Root(ref root_entry) if root_entry.0.product == product => {
                            Some(format!("Params({})", params_str(&root_entry.0.params)))
                        }
                        _ => None,
                    })
                    .collect();
                let suggestions_str = if suggestions.is_empty() {
                    format!(
                        "return the type {}. Try registering QueryRule({} for {}).",
                        product,
                        product,
                        params_str(&params),
                    )
                } else {
                    suggestions.sort();
                    format!(
            "can compute {} given input Params({}), but it can be produced using:\n  {}",
            product,
            params_str(&params),
            suggestions.join("\n  ")
          )
                };
                Err(format!("No installed QueryRules {suggestions_str}",))
            }
            _ => {
                let match_strs = subset_matches
                    .into_iter()
                    .map(|(e, _)| entry_with_deps_str(e))
                    .collect::<Vec<_>>();
                Err(format!(
                    "More than one set of @rules can compute {} for input Params({}):\n  {}",
                    product,
                    params_str(&params),
                    match_strs.join("\n  "),
                ))
            }
        }
    }

    ///
    /// TODO: It's not clear what is preventing `Node` implementations from ending up with non-Inner
    /// entries, but it would be good to make it typesafe instead.
    ///
    pub fn edges_for_inner(&self, entry: &Entry<R>) -> Option<RuleEdges<R>> {
        if let Entry::WithDeps(ref e) = entry {
            self.rule_dependency_edges.get(e).cloned()
        } else {
            panic!("not an inner entry! {entry:?}")
        }
    }

    pub fn validate_reachability(&self) -> Result<(), String> {
        if self.unreachable_rules.is_empty() {
            return Ok(());
        }

        // TODO: This method is currently a noop: see https://github.com/pantsbuild/pants/issues/10649.
        Ok(())
    }

    pub fn visualize(&self, f: &mut dyn io::Write) -> io::Result<()> {
        let display_args = DisplayForGraphArgs { multiline: true };
        let mut queries_strs = self
            .queries
            .iter()
            .map(|q| q.to_string())
            .collect::<Vec<String>>();
        queries_strs.sort();
        writeln!(f, "digraph {{")?;
        writeln!(f, "  // queries: {}", queries_strs.join(", "))?;
        writeln!(f, "  // root entries")?;
        let mut root_rule_strs = self
            .rule_dependency_edges
            .iter()
            .filter_map(|(k, deps)| match k.as_ref() {
                EntryWithDeps::Root(_) => {
                    let root_str = k.fmt_for_graph(display_args);
                    let mut dep_entries = deps
                        .all_dependencies()
                        .map(|d| visualize_entry(d, display_args))
                        .collect::<Vec<_>>();
                    dep_entries.sort();
                    let deps_with_attrs = dep_entries
                        .iter()
                        .cloned()
                        .filter(|d| d.attrs_str.is_some())
                        .map(|d| format!("\"{}\" {}", d.entry_str, d.attrs_str.unwrap()))
                        .collect::<Vec<String>>()
                        .join("\n");
                    Some(format!(
                        "    \"{}\" {}\n{}    \"{}\" -> {{{}}}",
                        root_str,
                        Palette::Blue.fmt_for_graph(display_args),
                        deps_with_attrs,
                        root_str,
                        dep_entries
                            .iter()
                            .cloned()
                            .map(|d| format!("\"{}\"", d.entry_str))
                            .collect::<Vec<String>>()
                            .join(" ")
                    ))
                }
                _ => None,
            })
            .collect::<Vec<String>>();
        root_rule_strs.sort();
        writeln!(f, "{}", root_rule_strs.join("\n"))?;

        writeln!(f, "  // internal entries")?;
        let mut internal_rule_strs = self
            .rule_dependency_edges
            .iter()
            .filter_map(|(k, deps)| match k.as_ref() {
                &EntryWithDeps::Rule(_) => {
                    let mut dep_entries = deps
                        .all_dependencies()
                        .map(|d| visualize_entry(d, display_args))
                        .collect::<Vec<_>>();
                    dep_entries.sort();
                    let deps_with_attrs = dep_entries
                        .iter()
                        .cloned()
                        .filter(|d| d.attrs_str.is_some())
                        .map(|d| format!("\"{}\" {}", d.entry_str, d.attrs_str.unwrap()))
                        .collect::<Vec<String>>()
                        .join("\n");
                    Some(format!(
                        "{}    \"{}\" -> {{{}}}",
                        deps_with_attrs,
                        k.fmt_for_graph(display_args),
                        dep_entries
                            .iter()
                            .cloned()
                            .map(|d| format!("\"{}\"", d.entry_str))
                            .collect::<Vec<String>>()
                            .join(" "),
                    ))
                }
                _ => None,
            })
            .collect::<Vec<String>>();
        internal_rule_strs.sort();
        writeln!(f, "{}", internal_rule_strs.join("\n"))?;
        writeln!(f, "}}")
    }
}

///
/// Records the dependency rules for a rule.
///
#[derive(Eq, PartialEq, Clone, Debug)]
pub struct RuleEdges<R: Rule> {
    dependencies: HashMap<DependencyKey<R::TypeId>, Intern<Entry<R>>>,
}

impl<R: Rule> RuleEdges<R> {
    pub fn entry_for(&self, dependency_key: &DependencyKey<R::TypeId>) -> Option<Intern<Entry<R>>> {
        self.dependencies.get(dependency_key).cloned()
    }

    pub fn all_dependencies(&self) -> impl Iterator<Item = &Intern<Entry<R>>> {
        self.dependencies.values()
    }
}

// TODO: We can't derive this due to https://github.com/rust-lang/rust/issues/26925, which
// unnecessarily requires `Rule: Default`.
impl<R: Rule> Default for RuleEdges<R> {
    fn default() -> Self {
        RuleEdges {
            dependencies: HashMap::default(),
        }
    }
}

#[cfg(test)]
mod tests;
