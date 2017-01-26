use std::path::Path;

// NB: Assuming unix allows us to zero-copy filesystem paths as bytes.
use std::os::unix::ffi::OsStrExt;

use graph::{Entry, Graph};
use core::{Field, Function, Key, TypeConstraint, TypeId, Value, Variants};
use externs::Externs;
use selectors::Selector;
use selectors;
use tasks::Tasks;
use types::Types;
use fs::{Dir, File, FSContext, Link, PathGlobs, PathGlob, PathStat, Stat};
use fs;


#[derive(Debug)]
pub struct Runnable {
  func: Function,
  args: Vec<Value>,
  cacheable: bool,
}

impl Runnable {
  pub fn func(&self) -> &Function {
    &self.func
  }

  pub fn args(&self) -> &Vec<Value> {
    &self.args
  }

  pub fn cacheable(&self) -> bool {
    self.cacheable
  }
}

#[derive(Debug)]
pub enum State<T> {
  Waiting(Vec<T>),
  Complete(Complete),
  Runnable(Runnable),
}

#[derive(Debug)]
pub enum Complete {
  Noop(&'static str, Option<Node>),
  Return(Value),
  Throw(Value),
}

pub struct StepContext<'g, 's> {
  entry: &'g Entry,
  graph: &'g Graph,
  tasks: &'s Tasks,
  types: &'s Types,
  externs: &'s Externs,
}

impl<'g, 't> StepContext<'g, 't> {
  /**
   * Create Nodes for each Task that might be able to compute the given product for the
   * given subject and variants.
   *
   * (analogous to NodeBuilder.gen_nodes)
   */
  fn gen_nodes(&self, subject: &Key, product: &TypeConstraint, variants: &Variants) -> Vec<Node> {
    // If the requested product is a Snapshot, use a Snapshot Node.
    if product == self.type_snapshot() {
      vec![
        // TODO: Hack... should have an intermediate Node to Select PathGlobs for the subject
        // before executing, and then treat this as an intrinsic. Otherwise, Snapshots for
        // different subjects but identical PathGlobs will cause redundant work.
        Node::Snapshot(
          Snapshot {
            subject: subject.clone(),
            product: product.clone(),
            variants: variants.clone(),
          }
        )
      ]
    } else {
      self.tasks.gen_tasks(subject.type_id(), product)
        .map(|tasks| {
          tasks.iter()
            .map(|task|
              Node::Task(
                Task {
                  subject: subject.clone(),
                  product: product.clone(),
                  variants: variants.clone(),
                  selector: task.clone(),
                }
              )
            )
            .collect()
        })
        .unwrap_or_else(|| Vec::new())
    }
  }

  fn get(&self, node: &Node) -> Option<&Complete> {
    self.graph.entry(node).and_then(|dep_entry| {
      // The entry exists. If it's a declared dep, return it immediately.
      if self.entry.dependencies().contains(&dep_entry.id()) {
        dep_entry.state()
      } else if self.entry.cyclic_dependencies().contains(&dep_entry.id()) {
        // Declared, but cyclic.
        Some(self.graph.cyclic_singleton())
      } else {
        // Undeclared. In theory we could still immediately return the dep here, but unfortunately
        // that occasionally allows Nodes to finish executing before all of their declared deps are
        // available.
        None
      }
    })
  }

  fn has_products(&self, item: &Value) -> bool {
    self.externs.satisfied_by(&self.types.has_products, item.type_id())
  }

  /**
   * Returns the `name` field of the given item.
   *
   * TODO: There are at least two hacks here. Because we don't have access to the appropriate
   * `str` type, we just assume that it has the same type as the name of the field. And more
   * importantly, there is no check that the object _has_ a name field.
   *
   * See https://github.com/pantsbuild/pants/issues/4207 about cleaning this up a bit.
   */
  fn field_name(&self, item: &Value) -> String {
    let name_val =
      self.project(
        item,
        &self.tasks.field_name,
        self.tasks.field_name.0.type_id()
      );
    self.externs.val_to_str(&name_val)
  }

  fn field_products(&self, item: &Value) -> Vec<Value> {
    self.project_multi(item, &self.tasks.field_products)
  }

  fn key_for(&self, val: &Value) -> Key {
    self.externs.key_for(val)
  }

  fn val_for(&self, key: &Key) -> Value {
    self.externs.val_for(key)
  }

  fn clone_val(&self, val: &Value) -> Value {
    self.externs.clone_val(val)
  }

  /**
   * NB: Panics on failure. Only recommended for use with built-in functions, such as
   * those configured in types::Types.
   */
  fn invoke_unsafe(&self, func: &Function, args: &Vec<Value>) -> Value {
    self.externs.invoke_runnable(func, args, false)
      .unwrap_or_else(|e| {
        panic!(
          "Core function `{}` failed: {}",
          self.externs.id_to_str(func.0),
          self.externs.val_to_str(&e)
        );
      })
  }

  /**
   * Stores a list of Keys, resulting in a Key for the list.
   */
  fn store_list(&self, items: Vec<&Value>, merge: bool) -> Value {
    self.externs.store_list(items, merge)
  }

  fn store_bytes(&self, item: &[u8]) -> Value {
    self.externs.store_bytes(item)
  }

  fn store_path(&self, item: &Path) -> Value {
    self.externs.store_bytes(item.as_os_str().as_bytes())
  }

  fn store_path_stat(&self, item: &PathStat) -> Value {
    let args =
      match item {
        &PathStat::Dir { ref path, ref stat } =>
          vec![self.store_path(path), self.store_dir(stat)],
        &PathStat::File { ref path, ref stat } =>
          vec![self.store_path(path), self.store_file(stat)],
      };
    self.invoke_unsafe(&self.types.construct_path_stat, &args)
  }

  fn store_dir(&self, item: &Dir) -> Value {
    let args = vec![self.store_path(item.0.as_path())];
    self.invoke_unsafe(&self.types.construct_dir, &args)
  }

  fn store_link(&self, item: &Link) -> Value {
    let args = vec![self.store_path(item.0.as_path())];
    self.invoke_unsafe(&self.types.construct_link, &args)
  }

  fn store_file(&self, item: &File) -> Value {
    let args = vec![self.store_path(item.0.as_path())];
    self.invoke_unsafe(&self.types.construct_file, &args)
  }

  fn store_snapshot(&self, item: &fs::Snapshot) -> Value {
    let path_stats: Vec<_> =
      item.path_stats.iter()
        .map(|ps| self.store_path_stat(ps))
        .collect();
    self.invoke_unsafe(
      &self.types.construct_snapshot,
      &vec![
        self.store_bytes(&item.fingerprint),
        self.store_list(path_stats.iter().collect(), false),
      ],
    )
  }

  /**
   * Calls back to Python for a satisfied_by check.
   */
  fn satisfied_by(&self, constraint: &TypeConstraint, cls: &TypeId) -> bool {
    self.externs.satisfied_by(constraint, cls)
  }

  /**
   * Calls back to Python to project a field.
   */
  fn project(&self, item: &Value, field: &Field, type_id: &TypeId) -> Value {
    self.externs.project(item, field, type_id)
  }

  /**
   * Calls back to Python to project a field representing a collection.
   */
  fn project_multi(&self, item: &Value, field: &Field) -> Vec<Value> {
    self.externs.project_multi(item, field)
  }

  fn project_multi_strs(&self, item: &Value, field: &Field) -> Vec<String> {
    self.externs.project_multi(item, field).iter()
      .map(|v| self.externs.val_to_str(v))
      .collect()
  }

  fn snapshot_root(&self) -> Dir {
    // TODO
    Dir(Path::new(".snapshot").to_owned())
  }

  fn build_root(&self) -> Dir {
    // TODO
    Dir(Path::new("").to_owned())
  }

  fn type_path_globs(&self) -> &TypeConstraint {
    &self.types.path_globs
  }

  fn type_snapshot(&self) -> &TypeConstraint {
    &self.types.snapshot
  }

  fn type_read_link(&self) -> &TypeConstraint {
    &self.types.read_link
  }

  fn type_directory_listing(&self) -> &TypeConstraint {
    &self.types.directory_listing
  }

  fn lift_path_globs(&self, item: &Value) -> Result<PathGlobs, String> {
    let include = self.project_multi_strs(item, &self.tasks.field_include);
    let exclude = self.project_multi_strs(item, &self.tasks.field_exclude);
    PathGlobs::create(&include, &exclude)
      .map_err(|e| {
        format!("Failed to parse PathGlobs for include({:?}), exclude({:?}): {}", include, exclude, e)
      })
  }

  fn lift_read_link(&self, item: &Value) -> String {
    panic!("TODO: Not implemented!");
  }

  fn lift_stats(&self, item: &Value) -> Vec<Stat> {
    panic!("TODO: Not implemented!");
  }

  /**
   * Creates a Throw state with the given exception message.
   */
  fn throw(&self, msg: String) -> Complete {
    Complete::Throw(self.externs.create_exception(msg))
  }
}

impl<'g, 't> FSContext<Node> for StepContext<'g, 't> {
  fn read_link(&self, link: &Link) -> Result<Vec<PathGlob>, Node> {
    let node =
      Node::create(
        Selector::select(self.type_read_link().clone()),
        self.key_for(&self.store_link(link)),
        Variants::default(),
      );
    let path =
      match self.get(&node) {
        Some(&Complete::Return(ref value)) =>
          self.lift_read_link(value),
        _ =>
          return Err(node),
      };
    // If the link destination can't be parsed as PathGlob(s), it is broken.
    Ok(PathGlob::create(&vec![path]).unwrap_or_else(|_| vec![]))
  }

  fn scandir(&self, dir: &Dir) -> Result<Vec<Stat>, Node> {
    let node =
      Node::create(
        Selector::select(self.type_directory_listing().clone()),
        self.key_for(&self.store_dir(dir)),
        Variants::default(),
      );
    match self.get(&node) {
      Some(&Complete::Return(ref value)) => Ok(self.lift_stats(value)),
      _ => Err(node),
    }
  }
}

/**
 * Defines executing a single step for the given context.
 */
trait Step {
  fn step(&self, context: StepContext) -> State<Node>;
}

/**
 * A Node that selects a product for a subject.
 *
 * A Select can be satisfied by multiple sources, but fails if multiple sources produce a value. The
 * 'variants' field represents variant configuration that is propagated to dependencies. When
 * a task needs to consume a product as configured by the variants map, it can pass variant_key,
 * which matches a 'variant' value to restrict the names of values selected by a SelectNode.
 */
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Select {
  subject: Key,
  variants: Variants,
  selector: selectors::Select,
}

impl Select {
  fn product(&self) -> &TypeConstraint {
    &self.selector.product
  }

  fn select_literal_single<'a>(
    &self,
    context: &StepContext,
    candidate: &'a Value,
    variant_value: Option<&str>
  ) -> bool {
    if !context.satisfied_by(&self.selector.product, candidate.type_id()) {
      return false;
    }
    return match variant_value {
      Some(vv) if context.field_name(candidate) != *vv =>
        // There is a variant value, and it doesn't match.
        false,
      _ =>
        true,
    };
  }

  /**
   * Looks for has-a or is-a relationships between the given value and the requested product.
   *
   * Returns the resulting product value, or None if no match was made.
   */
  fn select_literal(
    &self,
    context: &StepContext,
    candidate: Value,
    variant_value: Option<&str>
  ) -> Option<Value> {
    // Check whether the subject is-a instance of the product.
    if self.select_literal_single(context, &candidate, variant_value) {
      return Some(candidate)
    }

    // Else, check whether it has-a instance of the product.
    // TODO: returning only the first literal configuration of a given type/variant. Need to
    // define mergeability for products.
    if context.has_products(&candidate) {
      for child in context.field_products(&candidate) {
        if self.select_literal_single(context, &child, variant_value) {
          return Some(child);
        }
      }
    }
    return None;
  }
}

impl Step for Select {
  fn step(&self, context: StepContext) -> State<Node> {
    // TODO add back support for variants https://github.com/pantsbuild/pants/issues/4020
    let variants = &self.variants;

    // If there is a variant_key, see whether it has been configured; if not, no match.
    let variant_value: Option<&str> =
      match self.selector.variant_key {
        Some(ref variant_key) => {
          let variant_value = variants.find(variant_key);
          if variant_value.is_none() {
            return State::Complete(
              Complete::Noop("A matching variant key was not configured in variants.", None)
            )
          }
          variant_value
        },
        None => None,
      };

    // If the Subject "is a" or "has a" Product, then we're done.
    if let Some(literal_value) = self.select_literal(&context, context.val_for(&self.subject), variant_value) {
      return State::Complete(Complete::Return(literal_value));
    }

    // Else, attempt to use a configured task to compute the value.
    let mut dependencies = Vec::new();
    let mut matches: Vec<Value> = Vec::new();
    for dep_node in context.gen_nodes(&self.subject, self.product(), &self.variants) {
      match context.get(&dep_node) {
        Some(&Complete::Return(ref value)) => {
          if let Some(v) = self.select_literal(&context, context.clone_val(value), variant_value) {
            matches.push(v);
          }
        },
        Some(&Complete::Noop(_, _)) =>
          continue,
        Some(&Complete::Throw(ref msg)) =>
          return State::Complete(Complete::Throw(context.clone_val(msg))),
        None =>
          dependencies.push(dep_node),
      }
    }

    // If any dependencies were unavailable, wait for them; otherwise, determine whether
    // a value was successfully selected.
    if !dependencies.is_empty() {
      // A dependency has not run yet.
      return State::Waiting(dependencies);
    } else if matches.len() > 1 {
      // TODO: Multiple successful tasks are not currently supported. We should allow for this
      // by adding support for "mergeable" products. see:
      //   https://github.com/pantsbuild/pants/issues/2526
      return State::Complete(
        context.throw(format!("Conflicting values produced for subject and type."))
      );
    }

    match matches.pop() {
      Some(matched) =>
        // Statically completed!
        State::Complete(Complete::Return(matched)),
      None =>
        State::Complete(
          Complete::Noop("No task was available to compute the value.", None)
        ),
    }
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectLiteral {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectLiteral,
}

impl Step for SelectLiteral {
  fn step(&self, context: StepContext) -> State<Node> {
    State::Complete(Complete::Return(context.val_for(&self.selector.subject)))
  }
}

/**
 * A Node that selects the given Product for each of the items in `field` on `dep_product`.
 *
 * Begins by selecting the `dep_product` for the subject, and then selects a product for each
 * member of a collection named `field` on the dep_product.
 *
 * The value produced by this Node guarantees that the order of the provided values matches the
 * order of declaration in the list `field` of the `dep_product`.
 */
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectDependencies {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectDependencies,
}

impl SelectDependencies {
  fn dep_product<'a>(&self, context: &'a StepContext) -> Result<&'a Value, State<Node>> {
    // Request the product we need in order to request dependencies.
    let dep_product_node =
      Node::create(
        Selector::select(self.selector.dep_product),
        self.subject.clone(),
        self.variants.clone()
      );
    match context.get(&dep_product_node) {
      Some(&Complete::Return(ref value)) =>
        Ok(value),
      Some(&Complete::Noop(_, _)) =>
        Err(
          State::Complete(
            Complete::Noop("Could not compute {} to determine deps.", Some(dep_product_node))
          )
        ),
      Some(&Complete::Throw(ref msg)) =>
        Err(State::Complete(Complete::Throw(context.clone_val(msg)))),
      None =>
        Err(State::Waiting(vec![dep_product_node])),
    }
  }

  fn dep_node(&self, context: &StepContext, dep_subject: &Value) -> Node {
    // TODO: This method needs to consider whether the `dep_subject` is an Address,
    // and if so, attempt to parse Variants there. See:
    //   https://github.com/pantsbuild/pants/issues/4020

    let dep_subject_key = context.key_for(dep_subject);
    if self.selector.transitive {
      // After the root has been expanded, a traversal continues with dep_product == product.
      let mut selector = self.selector.clone();
      selector.dep_product = selector.product;
      Node::create(
        Selector::SelectDependencies(selector),
        dep_subject_key,
        self.variants.clone()
      )
    } else {
      Node::create(Selector::select(self.selector.product), dep_subject_key, self.variants.clone())
    }
  }

  fn store(&self, context: &StepContext, dep_product: &Value, dep_values: Vec<&Value>) -> Value {
    if self.selector.transitive && context.satisfied_by(&self.selector.product, dep_product.type_id())  {
      // If the dep_product is an inner node in the traversal, prepend it to the list of
      // items to be merged.
      // TODO: would be nice to do this in one operation.
      let prepend = context.store_list(vec![dep_product], false);
      let mut prepended = dep_values;
      prepended.insert(0, &prepend);
      context.store_list(prepended, self.selector.transitive)
    } else {
      // Not an inner node, or not a traversal.
      context.store_list(dep_values, self.selector.transitive)
    }
  }
}

impl Step for SelectDependencies {
  fn step(&self, context: StepContext) -> State<Node> {
    // Select the product holding the dependency list.
    let dep_product =
      match self.dep_product(&context) {
        Ok(dep_product) => dep_product,
        Err(state) => return state,
      };

    // The product and its dependency list are available.
    let mut dependencies = Vec::new();
    let mut dep_values: Vec<&Value> = Vec::new();
    for dep_subject in context.project_multi(&dep_product, &self.selector.field) {
      let dep_node = self.dep_node(&context, &dep_subject);
      match context.get(&dep_node) {
        Some(&Complete::Return(ref value)) =>
          dep_values.push(&value),
        Some(&Complete::Noop(_, _)) =>
          return State::Complete(
            context.throw(
              format!(
                "No source of explicit dep {}",
                dep_node.format(&context.externs)
              )
            )
          ),
        Some(&Complete::Throw(ref msg)) =>
          // NB: propagate thrown exception directly.
          return State::Complete(Complete::Throw(context.clone_val(msg))),
        None =>
          dependencies.push(dep_node),
      }
    }

    if dependencies.len() > 0 {
      State::Waiting(dependencies)
    } else {
      State::Complete(Complete::Return(self.store(&context, &dep_product, dep_values)))
    }
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectProjection {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectProjection,
}

impl Step for SelectProjection {
  fn step(&self, context: StepContext) -> State<Node> {
    // Request the product we need to compute the subject.
    let input_node =
      Node::create(
        Selector::select(self.selector.input_product),
        self.subject.clone(),
        self.variants.clone()
      );
    let dep_product =
      match context.get(&input_node) {
        Some(&Complete::Return(ref value)) =>
          value,
        Some(&Complete::Noop(_, _)) =>
          return State::Complete(
            Complete::Noop("Could not compute {} to project its field.", Some(input_node))
          ),
        Some(&Complete::Throw(ref msg)) =>
          return State::Complete(Complete::Throw(context.clone_val(msg))),
        None =>
          return State::Waiting(vec![input_node]),
      };

    // The input product is available: use it to construct the new Subject.
    let projected_subject =
      context.project(
        dep_product,
        &self.selector.field,
        &self.selector.projected_subject
      );

    // When the output product is available, return it.
    let output_node =
      Node::create(
        Selector::select(self.selector.product),
        context.key_for(&projected_subject),
        self.variants.clone()
      );
    match context.get(&output_node) {
      Some(&Complete::Return(ref value)) =>
        State::Complete(Complete::Return(context.clone_val(value))),
      Some(&Complete::Noop(_, _)) =>
        State::Complete(
          context.throw(
            format!(
              "No source of projected dependency {}",
              output_node.format(&context.externs)
            )
          )
        ),
      Some(&Complete::Throw(ref msg)) =>
        // NB: propagate thrown exception directly.
        State::Complete(Complete::Throw(context.clone_val(msg))),
      None =>
        State::Waiting(vec![output_node]),
    }
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Snapshot {
  subject: Key,
  product: TypeConstraint,
  variants: Variants,
}

impl Step for Snapshot {
  fn step(&self, context: StepContext) -> State<Node> {
    // Compute and parse PathGlobs for the subject.
    let path_globs_res = {
      let node =
        Node::create(
          Selector::select(context.type_path_globs().clone()),
          self.subject.clone(),
          self.variants.clone()
        );
      match context.get(&node) {
        Some(&Complete::Return(ref value)) =>
          context.lift_path_globs(value),
        Some(&Complete::Noop(_, _)) =>
          return State::Complete(
            Complete::Noop("Could not compute PathGlobs for input {}.", Some(node))
          ),
        Some(&Complete::Throw(ref msg)) =>
          // NB: propagate thrown exception directly.
          return State::Complete(Complete::Throw(context.clone_val(msg))),
        None =>
          return State::Waiting(vec![node]),
      }
    };

    let path_globs =
      match path_globs_res {
        Ok(pgs) => pgs,
        Err(e) => return State::Complete(context.throw(format!("Invalid filespecs: {}", e))),
      };

    // Recursively expand PathGlobs into PathStats.
    match context.expand(&path_globs) {
      Ok(path_stats) => {
        // The entire walk succeeded: ready to Snapshot.
        let snapshot_res =
          fs::Snapshot::create(
            &context.snapshot_root(),
            &context.build_root(),
            path_stats
          );
        match snapshot_res {
          Ok(snapshot) =>
            State::Complete(Complete::Return(context.store_snapshot(&snapshot))),
          Err(msg) =>
            State::Complete(context.throw(msg)),
        }
      },
      Err(dependencies) => {
        // The walk has additional dependencies: validate that none of them are
        // for failed Nodes. This is because the dependency gathering in FSContext
        // will only use a value if it is successful.
        for d in &dependencies {
          match context.get(&d) {
            Some(&Complete::Noop(..)) =>
              return State::Complete(
                context.throw(
                  format!(
                    "No source of snapshot dep: {}",
                    d.format(&context.externs)
                  )
                )
              ),
            Some(&Complete::Throw(ref msg)) =>
              return State::Complete(Complete::Throw(context.clone_val(msg))),
            _ => {},
          }
        }

        // All dependencies are valid. Declare them.
        State::Waiting(dependencies)
      }
    }
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Task {
  subject: Key,
  product: TypeConstraint,
  variants: Variants,
  selector: selectors::Task,
}

impl Step for Task {
  fn step(&self, context: StepContext) -> State<Node> {
    // Compute dependencies for the Node, or determine whether it is a Noop.
    let mut dependencies = Vec::new();
    let mut dep_values: Vec<&Value> = Vec::new();
    for selector in &self.selector.clause {
      let dep_node =
        Node::create(
          selector.clone(),
          self.subject.clone(),
          self.variants.clone()
        );
      match context.get(&dep_node) {
        Some(&Complete::Return(ref value)) =>
          dep_values.push(&value),
        Some(&Complete::Noop(_, _)) =>
          return State::Complete(
            Complete::Noop("Was missing (at least) input {}.", Some(dep_node))
          ),
        Some(&Complete::Throw(ref msg)) =>
          // NB: propagate thrown exception directly.
          return State::Complete(Complete::Throw(context.clone_val(msg))),
        None =>
          dependencies.push(dep_node),
      }
    }

    if !dependencies.is_empty() {
      // A clause was still waiting on dependencies.
      State::Waiting(dependencies)
    } else {
      // Ready to run!
      State::Runnable(Runnable {
        func: self.selector.func,
        args: dep_values.iter().map(|v| context.clone_val(v)).collect(),
        cacheable: self.selector.cacheable,
      })
    }
  }
}

// TODO: Likely that these could be inline struct definitions, rather than independently
// defined structs.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum Node {
  Select(Select),
  SelectLiteral(SelectLiteral),
  SelectDependencies(SelectDependencies),
  SelectProjection(SelectProjection),
  Snapshot(Snapshot),
  Task(Task),
}

impl Node {
  pub fn format(&self, externs: &Externs) -> String {
    match self {
      &Node::Select(_) => "Select".to_string(),
      &Node::SelectLiteral(_) => "Literal".to_string(),
      &Node::SelectDependencies(_) => "Dependencies".to_string(),
      &Node::SelectProjection(_) => "Projection".to_string(),
      &Node::Task(ref t) => format!("Task({})", externs.id_to_str(t.selector.func.0)),
      &Node::Snapshot(_) => "Snapshot".to_string(),
    }
  }

  pub fn subject(&self) -> &Key {
    match self {
      &Node::Select(ref s) => &s.subject,
      &Node::SelectLiteral(ref s) => &s.subject,
      &Node::SelectDependencies(ref s) => &s.subject,
      &Node::SelectProjection(ref s) => &s.subject,
      &Node::Task(ref t) => &t.subject,
      &Node::Snapshot(ref t) => &t.subject,
    }
  }

  pub fn product(&self) -> &TypeConstraint {
    match self {
      &Node::Select(ref s) => &s.selector.product,
      &Node::SelectLiteral(ref s) => &s.selector.product,
      &Node::SelectDependencies(ref s) => &s.selector.product,
      &Node::SelectProjection(ref s) => &s.selector.product,
      &Node::Task(ref t) => &t.selector.product,
      &Node::Snapshot(ref t) => &t.product,
    }
  }

  pub fn create(selector: Selector, subject: Key, variants: Variants) -> Node {
    match selector {
      Selector::Select(s) =>
        Node::Select(Select {
          subject: subject,
          variants: variants,
          selector: s,
        }),
      Selector::SelectLiteral(s) =>
        // NB: Intentionally ignores subject parameter to provide a literal subject.
        Node::SelectLiteral(SelectLiteral {
          subject: s.subject.clone(),
          variants: variants,
          selector: s,
        }),
      Selector::SelectDependencies(s) =>
        Node::SelectDependencies(SelectDependencies {
          subject: subject,
          variants: variants,
          selector: s,
        }),
      Selector::SelectProjection(s) =>
        Node::SelectProjection(SelectProjection {
          subject: subject,
          variants: variants,
          selector: s,
        }),
    }
  }

  pub fn step(
    &self,
    entry: &Entry,
    graph: &Graph,
    tasks: &Tasks,
    types: &Types,
    externs: &Externs,
  ) -> State<Node> {
    let context =
      StepContext {
        entry: entry,
        graph: graph,
        tasks: tasks,
        types: types,
        externs: externs,
      };
    match self {
      &Node::Select(ref n) => n.step(context),
      &Node::SelectDependencies(ref n) => n.step(context),
      &Node::SelectLiteral(ref n) => n.step(context),
      &Node::SelectProjection(ref n) => n.step(context),
      &Node::Task(ref n) => n.step(context),
      &Node::Snapshot(ref n) => n.step(context),
    }
  }
}
