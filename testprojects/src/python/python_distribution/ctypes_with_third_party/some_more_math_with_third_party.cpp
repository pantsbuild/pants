#include "some_more_math.hpp"

/* A simple C++11 header-only library for integration testing */
#include "rang.hpp"

/**
A C++11 library for integration testing that contains a library archive
(.dylib/.so) in addition to headers.

This snippet is taken from the README at https://github.com/USCiLab/cereal.
 */
#include <cereal/archives/binary.hpp>
#include <cereal/types/memory.hpp>
#include <cereal/types/unordered_map.hpp>

#include <irrXML.h>

#include <cstring>
#include <fstream>
#include <string>

struct MyRecord {
  uint8_t x = 1;
  uint8_t y = 2;
  float z;

  template <class Archive> void serialize(Archive &ar) { ar(x, y, z); }
};

struct SomeData {
  int32_t id;
  int data = 3;

  template <class Archive> void save(Archive &ar) const { ar(data); }

  template <class Archive> void load(Archive &ar) {
    static int32_t idGen = 0;
    id = idGen++;
    ar(data);
  }
};

int mangled_function(int x) {

  // cereal testing
  MyRecord myRecord;
  SomeData myData;

  // rang testing
  std::cout << "Testing 3rdparty C++..." << rang::style::bold << "Test worked!"
            << rang::style::reset << std::endl;

  return x ^ 3;
}

extern "C" int multiply_by_three(int x) { return mangled_function(x * 3); }

extern "C" const char *get_node_name_xml(const char *filename) {
  auto reader = irr::io::createIrrXMLReader(filename);
  std::string s;
  while (reader->read()) {
    s += ",";
    s += reader->getNodeName();
  }
  delete reader;
  /* TODO: This almost definitely leaks the string -- how to avoid this in ctypes? */
  return strdup(s.c_str());
}
