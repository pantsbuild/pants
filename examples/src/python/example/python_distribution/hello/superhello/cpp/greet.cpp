#include <Python.h>
#include <string>

string greet() {
  return "Super hello";
}

// You are in charge of any adapter code in terms of translating C/C++ methods into Python
// You can optionally instead use an external library's helper methods, or you can manually define
// them in a c/cpp file like below

PyObject* greet_impl(PyObject *) {
  string h = greet();
  return h;
}

static PyMethodDef greet_methods[] = {
  // The first property is the name exposed to python, the second is the C++ function name
  { "greet", (PyCFunction)greet_impl, METH_O, nullptr },

  // Terminate the array with an object containing nulls.
  { nullptr, nullptr, 0, nullptr }
};

PyMODINIT_FUNC PyInit_superhello() {
  return PyModule_Create(&greet_module);
}
