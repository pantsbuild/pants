#include <Python.h>

static PyObject * c_greet(PyObject *self, PyObject *args) {
  return Py_BuildValue("s", "Hello from C!");
}

static PyMethodDef Methods[] = {
  {"c_greet", c_greet, METH_VARARGS, "A greeting in the C language."},
  {NULL, NULL, 0, NULL}
};

#if PY_MAJOR_VERSION >= 3
  static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "c_greet", /* m_name */
    NULL,      /* m_doc */
    -1,        /* m_size */
    Methods,   /* m_methods */
    NULL,      /* m_slots */
    NULL,      /* m_traverse */
    NULL,      /* m_clear */
    NULL       /* m_free */
  };
#endif

#if PY_MAJOR_VERSION >= 3
  PyMODINIT_FUNC PyInit_c_greet(void) {
    return PyModule_Create(&moduledef);
  }
#else
  PyMODINIT_FUNC initc_greet(void) {
    (void) Py_InitModule("c_greet", Methods);
  }
#endif
