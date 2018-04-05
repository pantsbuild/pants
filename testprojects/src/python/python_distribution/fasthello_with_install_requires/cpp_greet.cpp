#include <Python.h>

static PyObject * cpp_greet(PyObject *self, PyObject *args) {
  return Py_BuildValue("s", "Hello from C++!");
}

static PyMethodDef Methods[] = {
  {"cpp_greet", cpp_greet, METH_VARARGS, "A greeting in the C++ language."},
  {NULL, NULL, 0, NULL}
};

PyMODINIT_FUNC initcpp_greet(void) {
  (void) Py_InitModule("cpp_greet", Methods);
}
