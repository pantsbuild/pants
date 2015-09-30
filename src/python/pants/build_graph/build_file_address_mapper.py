# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.address import Address, parse_spec
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot
from pants.base.build_file import BuildFile
from pants.build_graph.build_file_parser import BuildFileParser


# Note: Significant effort has been made to keep the types BuildFile, BuildGraph, Address, and
# Target separated appropriately.  The BuildFileAddressMapper is intended to have knowledge
# of just BuildFile, BuildFileParser and Address.
#
# Here are some guidelines to help maintain this abstraction:
#  - Use the terminology 'address' instead of 'target' in symbols and user messages
#  - Wrap exceptions from BuildFile and BuildFileParser with a subclass of AddressLookupError
#     so that callers do not have to reference those modules
#
# Note: 'spec' should not be a user visible term, substitute 'address' instead.
class BuildFileAddressMapper(object):
  """Maps addresses in the pants virtual address space to corresponding BUILD file declarations.
  """

  class AddressNotInBuildFile(AddressLookupError):
    """ Raised when an address cannot be found in an existing BUILD file."""
    pass

  class EmptyBuildFileError(AddressLookupError):
    """Raised if no addresses are defined in a BUILD file."""
    pass

  class InvalidBuildFileReference(AddressLookupError):
    """ Raised when a BUILD file does not exist at the address referenced."""
    pass

  class InvalidAddressError(AddressLookupError):
    """ Raised when an address cannot be parsed."""
    pass

  class BuildFileScanError(AddressLookupError):
    """ Raised when a problem was encountered scanning a tree of BUILD files."""

  def __init__(self, build_file_parser, build_file_type):
    """Create a BuildFileAddressMapper.

    :param build_file_parser: An instance of BuildFileParser
    :param build_file_type: A subclass of BuildFile used to construct and cache BuildFile objects
    """
    self._build_file_parser = build_file_parser
    self._spec_path_to_address_map_map = {}  # {spec_path: {address: addressable}} mapping
    self._build_file_type = build_file_type

  @property
  def root_dir(self):
    return self._build_file_parser.root_dir

  def _raise_incorrect_address_error(self, build_file, wrong_target_name, targets):
    """Search through the list of targets and return those which originate from the same folder
    which wrong_target_name resides in.

    :raises: A helpful error message listing possible correct target addresses.
    """
    def path_parts(build):  # Gets a tuple of directory, filename.
      build = str(build)
      slash = build.rfind('/')
      if slash < 0:
        return '', build
      return build[:slash], build[slash + 1:]

    def are_siblings(a, b):  # Are the targets in the same directory?
      return path_parts(a)[0] == path_parts(b)[0]

    valid_specs = []
    all_same = True
    # Iterate through all addresses, saving those which are similar to the wrong address.
    for target in targets:
      if are_siblings(target.build_file, build_file):
        possibility = (path_parts(target.build_file)[1], target.spec[target.spec.rfind(':'):])
        # Keep track of whether there are multiple BUILD files or just one.
        if all_same and valid_specs and possibility[0] != valid_specs[0][0]:
          all_same = False
        valid_specs.append(possibility)

    # Trim out BUILD extensions if there's only one anyway; no need to be redundant.
    if all_same:
      valid_specs = [('', tail) for head, tail in valid_specs]
    # Might be neat to sort by edit distance or something, but for now alphabetical is fine.
    valid_specs = [''.join(pair) for pair in sorted(valid_specs)]

    # Give different error messages depending on whether BUILD file was empty.
    if valid_specs:
      one_of = ' one of' if len(valid_specs) > 1 else ''  # Handle plurality, just for UX.
      raise self.AddressNotInBuildFile(
        '{target_name} was not found in BUILD file {build_file}. Perhaps you '
        'meant{one_of}: \n  {specs}'.format(target_name=wrong_target_name,
                                             build_file=build_file,
                                             one_of=one_of,
                                             specs='\n  '.join(valid_specs)))
    # There were no targets in the BUILD file.
    raise self.EmptyBuildFileError(
      ':{target_name} was not found in BUILD file {build_file}, because that '
      'BUILD file contains no addressable entities.'.format(target_name=wrong_target_name,
                                                             build_file=build_file))

  def resolve(self, address):
    """Maps an address in the virtual address space to an object.

    :param Address address: the address to lookup in a BUILD file
    :raises AddressLookupError: if the path to the address is not found.
    :returns: A tuple of the natively mapped BuildFileAddress and the Addressable it points to.
    """
    address_map = self._address_map_from_spec_path(address.spec_path)
    if address not in address_map:
      build_file = self._build_file_type.from_cache(self.root_dir, address.spec_path,
                                                    must_exist=False)
      self._raise_incorrect_address_error(build_file, address.target_name, address_map)
    else:
      return address_map[address]

  def resolve_spec(self, spec):
    """Converts a spec to an address and maps it using `resolve`"""
    try:
      address = Address.parse(spec)
    except ValueError as e:
      raise self.InvalidAddressError(e)
    _, addressable = self.resolve(address)
    return addressable

  def _address_map_from_spec_path(self, spec_path):
    """Returns a resolution map of all addresses in a "directory" in the virtual address space.

    :returns {Address: (Address, <resolved Object>)}:
    """
    if spec_path not in self._spec_path_to_address_map_map:
      try:
        try:
          build_file = self._build_file_type.from_cache(self.root_dir, spec_path)
        except BuildFile.BuildFileError as e:
          raise self.BuildFileScanError("{message}\n searching {spec_path}"
                                        .format(message=e,
                                                spec_path=spec_path))
        mapping = self._build_file_parser.address_map_from_build_file(build_file)
      except BuildFileParser.BuildFileParserError as e:
        raise AddressLookupError("{message}\n Loading addresses from '{spec_path}' failed."
                                 .format(message=e, spec_path=spec_path))

      address_map = {address: (address, addressed) for address, addressed in mapping.items()}
      self._spec_path_to_address_map_map[spec_path] = address_map
    return self._spec_path_to_address_map_map[spec_path]

  def addresses_in_spec_path(self, spec_path):
    """Returns only the addresses gathered by `address_map_from_spec_path`, with no values."""
    return self._address_map_from_spec_path(spec_path).keys()

  def from_cache(self, *args, **kwargs):
    """Return a BuildFile instance.  Args as per BuildFile.from_cache

    :returns: a BuildFile
    """
    return self._build_file_type.from_cache(*args, **kwargs)

  def spec_to_address(self, spec, relative_to=''):
    """A helper method for mapping a spec to the correct address.

    :param string spec: A spec to lookup in the map.
    :param string relative_to: Path the spec might be relative to
    :raises :class:`pants.base.address_lookup_error.AddressLookupError` If the BUILD file cannot be
            found in the path specified by the spec.
    :returns: A new Address instance.
    :rtype: :class:`pants.base.address.Address`
    """
    spec_path, name = parse_spec(spec, relative_to=relative_to)
    try:
      self.from_cache(self.root_dir, spec_path)
    except BuildFile.BuildFileError as e:
      raise self.InvalidBuildFileReference('{message}\n  when translating spec {spec}'
                                           .format(message=e, spec=spec))
    return Address(spec_path, name)

  def scan_buildfiles(self, root_dir, *args, **kwargs):
    """Looks for all BUILD files in root_dir or its descendant directories.

    :returns: an OrderedSet of BuildFile instances.
    """
    return self._build_file_type.scan_buildfiles(root_dir, *args, **kwargs)

  def specs_to_addresses(self, specs, relative_to=''):
    """The equivalent of `spec_to_address` for a group of specs all relative to the same path.
    :param spec: iterable of Addresses.
    :raises AddressLookupError: if the BUILD file cannot be found in the path specified by the spec
    """
    for spec in specs:
      yield self.spec_to_address(spec, relative_to=relative_to)

  def scan_addresses(self, root=None, spec_excludes=None):
    """Recursively gathers all addresses visible under `root` of the virtual address space.
    :raises AddressLookupError: if there is a problem parsing a BUILD file
    :param path root: defaults to the root directory of the pants project.
    """
    addresses = set()
    root = root or get_buildroot()
    try:
      for build_file in self._build_file_type.scan_buildfiles(root, spec_excludes=spec_excludes):
        for address in self.addresses_in_spec_path(build_file.spec_path):
          addresses.add(address)
    except BuildFile.BuildFileError as e:
      # Handle exception from BuildFile out of paranoia.  Currently, there is no way to trigger it.
      raise self.BuildFileScanError("{message}\n while scanning BUILD files in '{root}'."
                                    .format(message=e, root=root))
    return addresses
