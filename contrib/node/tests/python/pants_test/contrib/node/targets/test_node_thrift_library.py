from pants_test.test_base import TestBase
from pants.contrib.node.targets.node_thrift_library import NodeThriftLibrary


class NodeThriftLibraryTest(TestBase):
  def test_bin_executables_string(self) -> None:
    target = self.make_target(spec=':name', target_type=NodeThriftLibrary, package_name='name',
                              bin_executables='./cli.js')
    self.assertEqual('./cli.js', target.payload.bin_executables)

  def test_bin_executables_dict(self) -> None:
    target1 = self.make_target(spec=':name1', target_type=NodeThriftLibrary, package_name='name1',
                               bin_executables='./cli.js')
    target2 = self.make_target(spec=':name2', target_type=NodeThriftLibrary, package_name='name2',
                               bin_executables={"name2": "./cli.js"})
    self.assertNotEqual(target1, target2)
    self.assertEqual('./cli.js', target1.payload.bin_executables)
    self.assertEqual({'name2': './cli.js'}, target2.payload.bin_executables)
