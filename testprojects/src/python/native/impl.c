// coding=utf-8
// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#define PY_SSIZE_T_CLEAN
#include <Python.h>

static PyObject* name(PyObject* self) {
    return Py_BuildValue("s", "Professor Native");
}

static PyMethodDef hello_native_impl_funcs[] = {
    {"name", (PyCFunction)name, METH_VARARGS, "Return a name from native code."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef hello_native_impl_module = {
    PyModuleDef_HEAD_INIT,
    "hello.native.impl",
    NULL,
    -1,
    hello_native_impl_funcs
};

PyMODINIT_FUNC
PyInit_impl(void)
{
    return PyModule_Create(&hello_native_impl_module);
}
