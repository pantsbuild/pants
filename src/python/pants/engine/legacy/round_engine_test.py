# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools

from pants.base.exceptions import TaskError
from pants.engine.legacy.round_engine import Engine, RoundEngine
from pants.goal.goal import Goal
from pants.task.task import Task
from pants.testutil.engine.base_engine_test import EngineTestBase
from pants.testutil.test_base import TestBase


class EngineTest(EngineTestBase):
    class RecordingEngine(Engine):
        def __init__(self, action=None):
            super(EngineTest.RecordingEngine, self).__init__()
            self._action = action
            self._attempts = []

        @property
        def attempts(self):
            return self._attempts

        def attempt(self, context, goals):
            self._attempts.append((context, goals))
            if self._action:
                self._action()

    def setUp(self):
        super().setUp()
        self._context = self.context()

    def assert_attempt(self, engine, *goal_names):
        self.assertEqual(1, len(engine.attempts))

        context, goals = engine.attempts[0]
        self.assertEqual(self._context, context)
        self.assertEqual(self.as_goals(*goal_names), goals)

    def test_execute_success(self):
        engine = self.RecordingEngine()
        result = engine.execute(self._context, self.as_goals("one", "two"))
        self.assertEqual(0, result)
        self.assert_attempt(engine, "one", "two")

    def _throw(self, error):
        def throw():
            raise error

        return throw

    def test_execute_raise(self):
        engine = self.RecordingEngine(action=self._throw(TaskError()))
        result = engine.execute(self._context, self.as_goals("three"))
        self.assertEqual(1, result)
        self.assert_attempt(engine, "three")

    def test_execute_code(self):
        engine = self.RecordingEngine(action=self._throw(TaskError(exit_code=42)))
        result = engine.execute(self._context, self.as_goals("four", "five", "six"))
        self.assertEqual(42, result)
        self.assert_attempt(engine, "four", "five", "six")


class RoundEngineTest(EngineTestBase, TestBase):
    def setUp(self):
        super().setUp()

        self.set_options_for_scope("", explain=False)
        for outer in ["goal1", "goal2", "goal3", "goal4", "goal5"]:
            for inner in ["task1", "task2", "task3", "task4", "task5"]:
                self.set_options_for_scope(f"{outer}.{inner}", level="info", colors=False)

        self.engine = RoundEngine()
        self.actions = []
        self._context = None

    def tearDown(self):
        if self._context is not None:
            self.assertTrue(not self._context or self._context.is_unlocked())
        super().tearDown()

    def alternate_target_roots_action(self, tag):
        return "alternate_target_roots", tag, self._context

    def prepare_action(self, tag):
        return "prepare", tag, self._context

    def execute_action(self, tag):
        return "execute", tag, self._context

    def construct_action(self, tag):
        return "construct", tag, self._context

    def record(
        self,
        tag,
        product_types=None,
        required_data=None,
        optional_data=None,
        alternate_target_roots=None,
    ):
        class RecordingTask(Task):
            options_scope = tag

            @classmethod
            def product_types(cls):
                return product_types or []

            @classmethod
            def alternate_target_roots(cls, options, address_mapper, build_graph):
                self.actions.append(self.alternate_target_roots_action(tag))
                return alternate_target_roots

            @classmethod
            def prepare(cls, options, round_manager):
                for product in required_data or ():
                    round_manager.require_data(product)
                for product in optional_data or ():
                    round_manager.optional_data(product)
                self.actions.append(self.prepare_action(tag))

            def __init__(me, *args, **kwargs):
                super(RecordingTask, me).__init__(*args, **kwargs)
                self.actions.append(self.construct_action(tag))

            def execute(me):
                self.actions.append(self.execute_action(tag))

        return RecordingTask

    def install_task(
        self,
        name,
        product_types=None,
        goal=None,
        required_data=None,
        optional_data=None,
        alternate_target_roots=None,
    ):
        """Install a task to goal and return all installed tasks of the goal.

        This is needed to initialize tasks' context.
        """
        task_type = self.record(
            name, product_types, required_data, optional_data, alternate_target_roots
        )
        return super().install_task(name=name, action=task_type, goal=goal).task_types()

    def create_context(self, for_task_types=None, target_roots=None):
        self._context = self.context(for_task_types=for_task_types, target_roots=target_roots)
        self.assertTrue(self._context.is_unlocked())

    def assert_actions(self, *expected_execute_ordering):
        expected_pre_execute_actions = set()
        expected_execute_actions = []
        for action in expected_execute_ordering:
            expected_pre_execute_actions.add(self.alternate_target_roots_action(action))
            expected_pre_execute_actions.add(self.prepare_action(action))
            expected_execute_actions.append(self.construct_action(action))
            expected_execute_actions.append(self.execute_action(action))

        expected_execute_actions_length = len(expected_execute_ordering) * 2
        self.assertEqual(
            expected_pre_execute_actions, set(self.actions[:-expected_execute_actions_length])
        )
        self.assertEqual(expected_execute_actions, self.actions[-expected_execute_actions_length:])

    def test_lifecycle_ordering(self):
        task1 = self.install_task("task1", goal="goal1", product_types=["1"])
        task2 = self.install_task("task2", goal="goal1", product_types=["2"], required_data=["1"])
        task3 = self.install_task("task3", goal="goal3", product_types=["3"], required_data=["2"])
        task4 = self.install_task("task4", goal="goal4", required_data=["1", "2", "3"])
        self.create_context(for_task_types=task1 + task2 + task3 + task4)
        self.engine.attempt(self._context, self.as_goals("goal4"))
        self.assert_actions("task1", "task2", "task3", "task4")

    def test_lifecycle_ordering_install_order_invariant(self):
        # Here we swap the order of goal3 and goal4 task installation from the order in
        # `test_lifecycle_ordering` above.  We can't swap task1 and task2 since they purposefully
        # do have an implicit order dependence with a dep inside the same goal.
        task1 = self.install_task("task1", goal="goal1", product_types=["1"])
        task2 = self.install_task("task2", goal="goal1", product_types=["2"], required_data=["1"])
        task3 = self.install_task("task4", goal="goal4", required_data=["1", "2", "3"])
        task4 = self.install_task("task3", goal="goal3", product_types=["3"], required_data=["2"])
        self.create_context(for_task_types=task1 + task2 + task3 + task4)
        self.engine.attempt(self._context, self.as_goals("goal4"))
        self.assert_actions("task1", "task2", "task3", "task4")

    def test_inter_goal_dep(self):
        task1 = self.install_task("task1", goal="goal1", product_types=["1"])
        task2 = self.install_task("task2", goal="goal1", required_data=["1"])
        self.create_context(for_task_types=task1 + task2)
        self.engine.attempt(self._context, self.as_goals("goal1"))
        self.assert_actions("task1", "task2")

    def test_inter_goal_dep_self_cycle_ok(self):
        task = self.install_task("task1", goal="goal1", product_types=["1"], required_data=["1"])
        self.create_context(for_task_types=task)
        self.engine.attempt(self._context, self.as_goals("goal1"))
        self.assert_actions("task1")

    def test_inter_goal_dep_downstream(self):
        task1 = self.install_task("task1", goal="goal1", required_data=["1"])
        task2 = self.install_task("task2", goal="goal1", product_types=["1"])
        self.create_context(for_task_types=task1 + task2)
        with self.assertRaises(self.engine.TaskOrderError):
            self.engine.attempt(self._context, self.as_goals("goal1"))

    def test_missing_product(self):
        task = self.install_task("task1", goal="goal1", required_data=["1"])
        self.create_context(for_task_types=task)
        with self.assertRaises(self.engine.MissingProductError):
            self.engine.attempt(self._context, self.as_goals("goal1"))

    def test_missing_optional_product(self):
        task = self.install_task("task1", goal="goal1", optional_data=["1"])
        self.create_context(for_task_types=task)
        # Shouldn't raise, as the missing product is optional.
        self.engine.attempt(self._context, self.as_goals("goal1"))

    def test_goal_cycle_direct(self):
        task1 = self.install_task("task1", goal="goal1", required_data=["2"], product_types=["1"])
        task2 = self.install_task("task2", goal="goal2", required_data=["1"], product_types=["2"])
        self.create_context(for_task_types=task1 + task2)
        for goal in ("goal1", "goal2"):
            with self.assertRaises(self.engine.GoalCycleError):
                self.engine.attempt(self._context, self.as_goals(goal))

    def test_goal_cycle_indirect(self):
        task1 = self.install_task("task1", goal="goal1", required_data=["2"], product_types=["1"])
        task2 = self.install_task("task2", goal="goal2", required_data=["3"], product_types=["2"])
        task3 = self.install_task("task3", goal="goal3", required_data=["1"], product_types=["3"])
        self.create_context(for_task_types=task1 + task2 + task3)
        for goal in ("goal1", "goal2", "goal3"):
            with self.assertRaises(self.engine.GoalCycleError):
                self.engine.attempt(self._context, self.as_goals(goal))

    def test_goal_ordering_unconstrained_respects_cli_order(self):
        task1 = self.install_task("task1", goal="goal1")
        task2 = self.install_task("task2", goal="goal2")
        task3 = self.install_task("task3", goal="goal3")
        self.create_context(for_task_types=task1 + task2 + task3)
        for permutation in itertools.permutations(
            [("task1", "goal1"), ("task2", "goal2"), ("task3", "goal3")]
        ):
            self.actions = []
            self.engine.attempt(self._context, self.as_goals(*[goal for task, goal in permutation]))

            expected_execute_actions = [task for task, goal in permutation]
            self.assert_actions(*expected_execute_actions)

    def test_goal_ordering_constrained_conflicts_cli_order(self):
        task1 = self.install_task("task1", goal="goal1", required_data=["2"])
        task2 = self.install_task("task2", goal="goal2", product_types=["2"])
        self.create_context(for_task_types=task1 + task2)
        self.engine.attempt(self._context, self.as_goals("goal1", "goal2"))
        self.assert_actions("task2", "task1")

    def test_goal_ordering_mixed_constraints_and_cli_order(self):
        task1 = self.install_task("task1", goal="goal1")
        task2 = self.install_task("task2", goal="goal2")
        task3 = self.install_task("task3", goal="goal3")
        task4 = self.install_task("task4", goal="goal4", required_data=["5"])
        task5 = self.install_task("task5", goal="goal5", product_types=["5"])
        self.create_context(for_task_types=task1 + task2 + task3 + task4 + task5)
        self.engine.attempt(
            self._context, self.as_goals("goal1", "goal2", "goal4", "goal5", "goal3")
        )
        self.assert_actions("task1", "task2", "task5", "task4", "task3")

    def test_cli_goals_deduped(self):
        task1 = self.install_task("task1", goal="goal1")
        task2 = self.install_task("task2", goal="goal2")
        task3 = self.install_task("task3", goal="goal3")
        self.create_context(for_task_types=task1 + task2 + task3)
        self.engine.attempt(
            self._context, self.as_goals("goal1", "goal2", "goal1", "goal3", "goal2")
        )
        self.assert_actions("task1", "task2", "task3")

    def test_task_subclass_singletons(self):
        # Install the same task class twice (before/after Goal.clear()) and confirm that the
        # resulting task is equal.
        class MyTask(Task):
            pass

        def install():
            reg = super(RoundEngineTest, self).install_task(
                name="task1", action=MyTask, goal="goal1"
            )
            return reg.task_types()

        (task1_pre,) = install()
        Goal.clear()
        (task1_post,) = install()
        self.assertEqual(task1_pre, task1_post)

    def test_replace_target_roots(self):
        task1 = self.install_task("task1", goal="goal1")
        task2 = self.install_task("task2", goal="goal2", alternate_target_roots=[42])
        self.create_context(for_task_types=task1 + task2)
        self.assertEqual([], self._context.target_roots)
        self.engine.attempt(self._context, self.as_goals("goal1", "goal2"))
        self.assertEqual([42], self._context.target_roots)

    def test_replace_target_roots_conflict(self):
        task1 = self.install_task("task1", goal="goal1", alternate_target_roots=[42])
        task2 = self.install_task("task2", goal="goal2", alternate_target_roots=[1, 2])
        self.create_context(for_task_types=task1 + task2)
        with self.assertRaises(self.engine.TargetRootsReplacement.ConflictingProposalsError):
            self.engine.attempt(self._context, self.as_goals("goal1", "goal2"))

    def test_replace_target_roots_to_empty_list(self):
        task1 = self.install_task("task1", goal="goal1")
        task2 = self.install_task("task2", goal="goal2", alternate_target_roots=[])
        target = self.make_target("t")
        self.create_context(for_task_types=task1 + task2, target_roots=[target])

        self.engine.attempt(self._context, self.as_goals("goal1", "goal2"))

        self.assertEqual([], self._context.target_roots)
