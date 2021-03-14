use std::sync::Arc;

use super::PyExecutor;
use cpython::{exc, py_class, PyErr, PyObject, PyResult, PyString};
use parking_lot::Mutex;
use testutil_mock::{StubCAS, StubCASBuilder};

py_class!(pub class PyStubCASBuilder |py| {
  data builder: Arc<Mutex<Option<StubCASBuilder>>>;

  def always_errors(&self) -> PyResult<PyObject> {
    let mut builder_opt = self.builder(py).lock();
    let builder = builder_opt
      .take()
      .ok_or_else(|| PyErr::new::<exc::Exception, _>(py, (PyString::new(py, "unable to unwrap StubCASBuilder"),)))?
      .always_errors();
    *builder_opt = Some(builder);
    Ok(py.None())
  }

  def build(&self, executor: PyExecutor) -> PyResult<PyStubCAS> {
    let executor = executor.executor(py);
    executor.enter(|| {
      let mut builder_opt = self.builder(py).lock();
      let builder = builder_opt
        .take()
        .ok_or_else(|| PyErr::new::<exc::Exception, _>(py, (PyString::new(py, "unable to unwrap StubCASBuilder"),)))?;
      let cas = builder.build();
      PyStubCAS::create_instance(py, cas)
    })
  }
});

py_class!(pub class PyStubCAS |py| {
  data server: StubCAS;

  @classmethod
  def builder(cls) -> PyResult<PyStubCASBuilder> {
    let builder = StubCAS::builder();
    PyStubCASBuilder::create_instance(py, Arc::new(Mutex::new(Some(builder))))
  }

  def address(&self) -> PyResult<PyString> {
    let server = self.server(py);
    let address = server.address();
    Ok(PyString::new(py, &address))
  }
});
