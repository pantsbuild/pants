// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;

use petgraph::graph::{DiGraph, Graph};
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::wrap_pyfunction;

mod nailgun;
mod testutil;

#[pymodule]
fn native_engine_pyo3(py: Python, m: &PyModule) -> PyResult<()> {
  self::nailgun::register(py, m)?;
  self::testutil::register(m)?;

  m.add_class::<PyExecutor>()?;

  m.add_function(wrap_pyfunction!(strongly_connected_components, m)?)
    .unwrap();

  Ok(())
}

// TODO: Would be nice to be able to accept any Python object, rather than only u32.
#[pyfunction]
fn strongly_connected_components(
  adjacency_lists: HashMap<u32, Vec<u32>>,
) -> PyResult<Vec<Vec<u32>>> {
  let mut graph: DiGraph<u32, (), u32> = Graph::new();
  let mut node_ids = HashMap::new();

  for (node, adjacency_list) in adjacency_lists {
    let node_id = node_ids
      .entry(node)
      .or_insert_with(|| graph.add_node(node))
      .clone();
    for dependency in adjacency_list {
      let dependency_id = node_ids
        .entry(dependency)
        .or_insert_with(|| graph.add_node(dependency));
      graph.add_edge(node_id, *dependency_id, ());
    }
  }

  Ok(
    petgraph::algo::tarjan_scc(&graph)
      .into_iter()
      .map(|component| {
        component
          .into_iter()
          .map(|node_id| graph[node_id])
          .collect::<Vec<_>>()
      })
      .collect(),
  )
}

#[pyclass]
#[derive(Debug, Clone)]
struct PyExecutor {
  executor: task_executor::Executor,
}

#[pymethods]
impl PyExecutor {
  #[new]
  fn __new__(core_threads: usize, max_threads: usize) -> PyResult<Self> {
    task_executor::Executor::global(core_threads, max_threads)
      .map(|executor| PyExecutor { executor })
      .map_err(PyException::new_err)
  }
}
