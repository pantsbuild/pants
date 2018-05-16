#include <Python.h>

static PyObject * c_greet(PyObject *self, PyObject *args) {
  return Py_BuildValue("s", "Hello from C!");
}

static PyMethodDef Methods[] = {
  {"c_greet", c_greet, METH_VARARGS, "A greeting in the C language."},
  {NULL, NULL, 0, NULL}
};

PyMODINIT_FUNC initc_greet(void) {
  (void) Py_InitModule("c_greet", Methods);
}
