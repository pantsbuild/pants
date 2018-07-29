// coding=utf-8
// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#include <Python.h>

static PyObject *hello(PyObject *self, PyObject *args) {
  /* FIXME: make this depend on some env var we pass in!? */
  return Py_BuildValue("s", "Hello from C!");
}

static PyMethodDef Methods[] = {
  {"hello", hello, METH_VARARGS, "A greeting in the C language."},
  {NULL, NULL, 0, NULL}
};

PyMODINIT_FUNC inithello(void) {
  (void) Py_InitModule("hello", Methods);
}
