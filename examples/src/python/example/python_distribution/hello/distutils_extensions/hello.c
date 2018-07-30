// coding=utf-8
// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#include <Python.h>

#ifdef PANTS_PYTHON_DIST
static const char *hello_str = "Hello from Pants!";
#else
static const char *hello_str = "Hello from outside of Pants!";
#endif

    static PyObject *
    hello(PyObject *self, PyObject *args) {
  return Py_BuildValue("s", hello_str);
}

static PyMethodDef Methods[] = {
  {"hello", hello, METH_VARARGS, "A greeting in the C language."},
  {NULL, NULL, 0, NULL}
};

PyMODINIT_FUNC inithello(void) {
  (void) Py_InitModule("hello", Methods);
}
