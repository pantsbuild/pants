# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, Generator, Iterable, Tuple, Type, cast

from pants.util.meta import frozen_after_init
from pants.util.objects import TypeConstraint


@frozen_after_init
@dataclass(unsafe_hash=True)
class Get:
  """Experimental synchronous generator API.

  May be called equivalently as either:
    # verbose form: Get(product, subject_declared_type, subject)
    # shorthand form: Get(product, subject_declared_type(<constructor args for subject>))
  """
  product: Type
  subject_declared_type: Type
  subject: Any

  def __await__(self) -> Generator[Any, Any, Any]:
    """Allow a Get to be `await`ed within an `async` method, returning a strongly-typed result.

    The `yield`ed value `self` is interpreted by the engine within `extern_generator_send()` in
    `native.py`. This class will yield a single Get instance, which is converted into
    `PyGeneratorResponse::Get` from `externs.rs` via the python `cffi` library and the rust
    `cbindgen` crate.

    This is how this method is eventually called:
    - When the engine calls an `async def` method decorated with `@rule`, an instance of
      `types.CoroutineType` is created.
    - The engine will call `.send(None)` on the coroutine, which will either:
      - raise StopIteration with a value (if the coroutine `return`s), or
      - return a `Get` instance to the engine (if the rule instead called `await Get(...)`).
    - The engine will fulfill the `Get` request to produce `x`, then call `.send(x)` and repeat the
      above until StopIteration.

    See more information about implementing this method at
    https://www.python.org/dev/peps/pep-0492/#await-expression.
    """
    result = yield self
    return result

  def __init__(self, *args: Any) -> None:
    if len(args) not in (2, 3):
      raise ValueError(
        f'Expected either two or three arguments to {Get.__name__}; got {args}.'
      )
    if len(args) == 2:
      product, subject = args

      if isinstance(subject, (type, TypeConstraint)):
        raise TypeError(dedent("""\
          The two-argument form of Get does not accept a type as its second argument.

          args were: Get({args!r})

          Get.create_statically_for_rule_graph() should be used to generate a Get() for
          the `input_gets` field of a rule. If you are using a `yield Get(...)` in a rule
          and a type was intended, use the 3-argument version:
          Get({product!r}, {subject_type!r}, {subject!r})
          """.format(args=args, product=product, subject_type=type(subject), subject=subject)
        ))

      subject_declared_type = type(subject)
    else:
      product, subject_declared_type, subject = args

    self.product = product
    self.subject_declared_type = subject_declared_type
    self.subject = subject

  @staticmethod
  def extract_constraints(call_node):
    """Parses a `Get(..)` call in one of its two legal forms to return its type constraints.

    :param call_node: An `ast.Call` node representing a call to `Get(..)`.
    :return: A tuple of product type id and subject type id.
    """
    def render_args():
      return ', '.join(
        # Dump the Name's id to simplify output when available, falling back to the name of the
        # node's class.
        getattr(a, 'id', type(a).__name__)
        for a in call_node.args)

    if len(call_node.args) == 2:
      product_type, subject_constructor = call_node.args
      if not isinstance(product_type, ast.Name) or not isinstance(subject_constructor, ast.Call):
        raise ValueError(
          'Two arg form of {} expected (product_type, subject_type(subject)), but '
                        'got: ({})'.format(Get.__name__, render_args()))
      return (product_type.id, subject_constructor.func.id)
    elif len(call_node.args) == 3:
      product_type, subject_declared_type, _ = call_node.args
      if not isinstance(product_type, ast.Name) or not isinstance(subject_declared_type, ast.Name):
        raise ValueError(
          'Three arg form of {} expected (product_type, subject_declared_type, subject), but '
                        'got: ({})'.format(Get.__name__, render_args()))
      return (product_type.id, subject_declared_type.id)
    else:
      raise ValueError('Invalid {}; expected either two or three args, but '
                      'got: ({})'.format(Get.__name__, render_args()))

  @classmethod
  def create_statically_for_rule_graph(cls, product_type, subject_type) -> 'Get':
    """Construct a `Get` with a None value.

    This method is used to help make it explicit which `Get` instances are parsed from @rule bodies
    and which are instantiated during rule execution.
    """
    return cls(product_type, subject_type, None)


@frozen_after_init
@dataclass(unsafe_hash=True)
class MultiGet:
  """Can be constructed with an iterable of `Get()`s and `await`ed to evaluate them in parallel."""
  gets: Tuple[Get, ...]

  def __await__(self) -> Generator[Any, Any, Tuple[Any, ...]]:
    """Yield a tuple of Get instances with the same subject/product type pairs all at once.

    The `yield`ed value `self.gets` is interpreted by the engine within `extern_generator_send()` in
    `native.py`. This class will yield a tuple of Get instances, which is converted into
    `PyGeneratorResponse::GetMulti` from `externs.rs`.

    The engine will fulfill these Get instances in parallel, and return a tuple of T
    instances to this method, which then returns this tuple to the `@rule` which called
    `await MultiGet(Get(T, ...) for ... in ...)`.
    """
    result = yield self.gets
    return cast(Tuple[Any, ...], result)

  def __init__(self, gets: Iterable[Get]) -> None:
    """Create a MultiGet from a generator expression.

    This constructor will infer this class's _Product parameter from the input `gets`.
    """
    self.gets = tuple(gets)


@frozen_after_init
@dataclass(unsafe_hash=True)
class Params:
  """A set of values with distinct types.

  Distinct types are enforced at consumption time by the rust type of the same name.
  """
  params: Tuple[Any, ...]

  def __init__(self, *args: Any) -> None:
    self.params = tuple(args)
