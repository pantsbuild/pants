from future.utils import text_type

from pants.engine.rules import rule, RootRule
from pants.util.objects import datatype
from pants_test.test_base import TestBase

class FullName(datatype([
  ("full_name", text_type),
])): pass

class FirstName(datatype([
  ("name", text_type),
])): pass

class Greeting(datatype([
  ("greet", text_type),
])): pass

@rule(FirstName, [FullName])
def full_name_to_first_name(full_name):
  return FirstName(full_name.full_name.split()[0])

@rule(Greeting, [FirstName])
def first_name_to_greeting(name):
  return Greeting(text_type("Hi, %s"%(name.name)))

@rule(Greeting, [FullName])
def full_name_to_greeting(full_name):
  return Greeting(text_type("Hi, %s"%(full_name.full_name.split()[0])))

class FSTest(TestBase):

  @classmethod
  def rules(cls):
    return [
      RootRule(FullName),
      RootRule(FirstName),
      full_name_to_first_name,
      first_name_to_greeting,
      full_name_to_greeting,
    ]

  def test_make_greeting(self):
    products = self.scheduler.product_request(Greeting, subjects=[FullName(text_type("First Name"))])
    self.assertEquals(products, [Greeting(text_type("Hi, First"))])
