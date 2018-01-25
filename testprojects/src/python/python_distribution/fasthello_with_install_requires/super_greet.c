#include <Python.h>

static PyObject * super_greet(PyObject *self, PyObject *args) {
  return Py_BuildValue("s", "Super hello");
}

static PyMethodDef Methods[] = {
  {"super_greet", super_greet, METH_VARARGS, "A super greeting"},
  {NULL, NULL, 0, NULL}
};

PyMODINIT_FUNC initsuper_greet(void) {
  (void) Py_InitModule("super_greet", Methods);
}
