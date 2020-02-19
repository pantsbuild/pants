# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import threading


class Storage(threading.local):
    def __init__(self, rel_path):
        self.clear(rel_path)

    def clear(self, rel_path):
        self.rel_path = rel_path
        self.objects_by_name = dict()
        self.objects = []

    def add(self, obj, name=None):
        if name is not None:
            # NB: `src/python/pants/engine/mapper.py` will detect an overwritten object later.
            self.objects_by_name[name] = obj
        self.objects.append(obj)

    def add_if_not_exists(self, name, obj_creator):
        if name is None:
            raise ValueError("Method requires a `name`d object.")
        obj = self.objects_by_name.get(name)
        if obj is None:
            obj = self.objects_by_name[name] = obj_creator()
        return obj


class ParseContext:
    """The build file context that context aware objects - aka BUILD macros - operate against.

    All fields of the ParseContext must be assumed to be mutable by macros, and should
    thus only be consumed in the context of a macro's `__call__` method (rather than
    in its `__init__`).
    """

    def __init__(self, rel_path, type_aliases):
        """Create a ParseContext.

        :param rel_path: The (build file) path that the parse is currently operating on: initially None.
        :param type_aliases: A dictionary of alias name strings or alias classes to a callable
          constructor for the alias.
        """

        self._type_aliases = type_aliases
        self._storage = Storage(rel_path)

    def create_object(self, alias, *args, **kwargs):
        """Constructs the type with the given alias using the given args and kwargs.

        NB: aliases may be the alias' object type itself if that type is known.

        :API: public

        :param alias: Either the type alias or the type itself.
        :type alias: string|type
        :param *args: These pass through to the underlying callable object.
        :param **kwargs: These pass through to the underlying callable object.
        :returns: The created object.
        """
        object_type = self._type_aliases.get(alias)
        if object_type is None:
            raise KeyError("There is no type registered for alias {0}".format(alias))
        return object_type(*args, **kwargs)

    def create_object_if_not_exists(self, alias, name=None, *args, **kwargs):
        """Constructs the type with the given alias using the given args and kwargs.

        NB: aliases may be the alias' object type itself if that type is known.

        :API: public

        :param alias: Either the type alias or the type itself.
        :type alias: string|type
        :param *args: These pass through to the underlying callable object.
        :param **kwargs: These pass through to the underlying callable object.
        :returns: The created object, or an existing object with the same `name`.
        """
        if name is None:
            raise ValueError("Method requires an object `name`.")
        obj_creator = functools.partial(self.create_object, alias, name=name, *args, **kwargs)
        return self._storage.add_if_not_exists(name, obj_creator)

    @property
    def rel_path(self):
        """Relative path from the build root to the BUILD file the context aware object is called
        in.

        :API: public

        :rtype string
        """
        return self._storage.rel_path
