#include "some_more_math.hpp"

/* A simple C++11 header-only library for integration testing */
#include "rang.hpp"

/**
A C++11 library for integration testing that contains a library archive (.dylib/.so)
in addition to headers.

This snippet is taken from the README at https://github.com/USCiLab/cereal.
 */
#include <cereal/types/unordered_map.hpp>
#include <cereal/types/memory.hpp>
#include <cereal/archives/binary.hpp>
#include <fstream>

struct MyRecord
{
  uint8_t x = 1;
  uint8_t y = 2;
  float z;

  template <class Archive>
  void serialize( Archive & ar )
  {
    ar( x, y, z );
  }
};

struct SomeData
{
  int32_t id;
  std::shared_ptr<std::unordered_map<uint32_t, MyRecord>> data;

  template <class Archive>
  void save( Archive & ar ) const
  {
    ar( data );
  }

  template <class Archive>
  void load( Archive & ar )
  {
    static int32_t idGen = 0;
    id = idGen++;
    ar( data );
  }
};


int mangled_function(int x) {

	// cereal testing
	std::ofstream os("out.cereal", std::ios::binary);
	cereal::BinaryOutputArchive archive( os );
	SomeData myData;
	archive( myData );

	// rang testing
	std::cout << "Plain text\n"
         << rang::style::bold << "Text from 3rdparty!"
         << rang::style::reset << std::endl;
	return x ^ 3;
}

extern "C" int multiply_by_three(int x) { return mangled_function(x * 3); }
