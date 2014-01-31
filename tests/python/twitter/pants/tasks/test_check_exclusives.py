from twitter.pants.base import Config
from twitter.pants.goal import Context
from twitter.pants.testutils import MockTarget
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.check_exclusives import CheckExclusives
from twitter.pants.testutils.base_mock_target_test import BaseMockTargetTest


class CheckExclusivesTest(BaseMockTargetTest):
  """Test of the CheckExclusives task."""

  @classmethod
  def setUpClass(cls):
     cls.config = Config.load()

  def setupTargets(self):
    a = MockTarget('a', exclusives={'a': '1', 'b': '1'})
    b = MockTarget('b', exclusives={'a': '1'})
    c = MockTarget('c', exclusives = {'a': '2'})
    d = MockTarget('d', dependencies=[a, b])
    e = MockTarget('e', dependencies=[a, c], exclusives={'c': '1'})
    return a, b, c, d, e

  def test_check_exclusives(self):
    a, b, c, d, e = self.setupTargets()
    context = Context(CheckExclusivesTest.config, options={}, run_tracker=None, target_roots=[d, e])
    check_exclusives_task = CheckExclusives(context, signal_error=True)
    try:
      check_exclusives_task.execute([d, e])
      self.fail("Expected a conflicting exclusives exception to be thrown.")
    except TaskError:
      pass

  def test_classpath_compatibility(self):
    # test the compatibility checks for different exclusive groups.
    a = MockTarget('a', exclusives={'a': '1', 'b': '1'})
    b = MockTarget('b', exclusives={'a': '1', 'b': '<none>'})
    c = MockTarget('c', exclusives = {'a': '2', 'b': '2'})
    d = MockTarget('d')

    context = Context(CheckExclusivesTest.config, options={}, run_tracker=None, target_roots=[a, b, c, d])
    context.products.require_data('exclusives_groups')
    check_exclusives_task = CheckExclusives(context, signal_error=True)
    check_exclusives_task.execute([a, b, c, d])
    egroups = context.products.get_data('exclusives_groups')
    # Expected compatibility:
    # a is compatible with nothing but itself.
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[a], egroups.target_to_key[a]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[a], egroups.target_to_key[b]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[a], egroups.target_to_key[d]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[a], egroups.target_to_key[c]))

    # b is compatible with itself and a.
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[b], egroups.target_to_key[a]))
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[b], egroups.target_to_key[b]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[b], egroups.target_to_key[c]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[b], egroups.target_to_key[d]))

    # c is compatible with nothing but itself
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[c], egroups.target_to_key[c]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[c], egroups.target_to_key[a]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[c], egroups.target_to_key[b]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[c], egroups.target_to_key[d]))

    # d is compatible with everything.
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[d], egroups.target_to_key[a]))
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[d], egroups.target_to_key[b]))
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[d], egroups.target_to_key[c]))
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[d], egroups.target_to_key[d]))


  def testClasspathUpdates(self):
    # Check that exclusive groups classpaths accumulate properly.
    a = MockTarget('a', exclusives={'a': '1', 'b': '1'})
    b = MockTarget('b', exclusives={'a': '1', 'b': '<none>'})
    c = MockTarget('c', exclusives = {'a': '2', 'b': '2'})
    d = MockTarget('d')

    context = Context(CheckExclusivesTest.config, options={}, run_tracker=None, target_roots=[a, b, c, d])
    context.products.require_data('exclusives_groups')
    check_exclusives_task = CheckExclusives(context, signal_error=True)
    check_exclusives_task.execute([a, b, c, d])
    egroups = context.products.get_data('exclusives_groups')

    egroups.set_base_classpath_for_group("a=1,b=1", [ "a1","b1"])
    egroups.set_base_classpath_for_group("a=1,b=<none>", [ "a1" ])
    egroups.set_base_classpath_for_group("a=2,b=2", [ "a2","b2"])
    egroups.set_base_classpath_for_group("a=<none>,b=<none>", ["none"])
    egroups.update_compatible_classpaths(None, ["update_without_group"])
    egroups.update_compatible_classpaths("a=<none>,b=<none>", ["update_all"])
    egroups.update_compatible_classpaths("a=1,b=<none>", [ "update_a1bn"])
    egroups.update_compatible_classpaths("a=2,b=2", [ "update_only_a2b2"])
    self.assertEquals(egroups.get_classpath_for_group("a=2,b=2"),
             [ "a2", "b2", "update_without_group", "update_all", "update_only_a2b2"])
    self.assertEquals(egroups.get_classpath_for_group("a=1,b=1"),
              [ "a1", "b1", "update_without_group", "update_all", "update_a1bn" ])
    self.assertEquals(egroups.get_classpath_for_group("a=1,b=<none>"),
              [ "a1", "update_without_group", "update_all", "update_a1bn" ])
    self.assertEquals(egroups.get_classpath_for_group("a=<none>,b=<none>"),
              [ "none", "update_without_group", "update_all" ])

    # make sure repeated additions of the same thing are idempotent.
    egroups.update_compatible_classpaths("a=1,b=1", ["a1", "b1", "xxx"])
    self.assertEquals(egroups.get_classpath_for_group("a=1,b=1"),
              [ "a1", "b1", "update_without_group", "update_all", "update_a1bn", "xxx" ])






