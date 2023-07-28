# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Utilities for accessing the readme.com API.

Since they don't have a Python SDK.

This is not a general purpose SDK: It only covers the parts we need, namely
Categories and Docs, and within those, only the fields we care about.

Note: The readme.com API is a little confusing wrt to ids and slugs.
 You access a Category or Doc object via its slug. But those objects reference other objects by id.
 For example, A Doc references its category via the `category` field, which contains an id.
 There is no easy way to go directly from an id to an object: You have to enumerate all
 the objects. The one useful exception is that when you retrieve all the Docs in a Category,
 you get a list of reference objects, each of which includes the id *and* the slug.
 The fields containing ids do not have an "_id" suffix, for consistency with the over-the-wire
 field names. So assume that any reference field contains an id, unless its name is "slug".
"""

from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass
from typing import Any, TypeVar, Union, cast

import requests

logger = logging.getLogger(__name__)


_API_URL_PREFIX = "https://dash.readme.io/api/v1/"


ApiResponse = Union[dict, list, None]


T = TypeVar("T", bound="ReadmeEntity")  # Entity type.
F = TypeVar("F")  # Field type.


@dataclass(frozen=True, slots=True)
class ReadmeEntity:
    _id: str

    @property
    def id(self):
        return self._id

    @classmethod
    def from_api_response(cls: type[T], data: dict) -> T:
        init_kwargs = {}
        for field in dataclasses.fields(cls):
            if field.name not in data and field.default == dataclasses.MISSING:
                raise KeyError(field.name)
            init_kwargs[field.name] = cls.field_value_from_api_response(
                field.name, field.type, data.get(field.name, field.default)
            )
        return cls(**init_kwargs)

    @classmethod
    def field_value_from_api_response(cls, field_name: str, field_type: type[F], val: Any) -> F:
        """Subclasses can override to handle specific fields specially."""
        return cast(F, val)


@dataclass(frozen=True, slots=True)
class Category(ReadmeEntity):
    slug: str
    title: str
    order: int

    def __str__(self):
        return f"Category(id={self.id}, slug={self.slug}, title={self.title}, order={self.order})"


@dataclass(frozen=True, slots=True)
class DocRef(ReadmeEntity):
    """A reference to a doc, without its body and other details."""

    slug: str
    title: str
    order: int
    hidden: bool
    children: tuple[DocRef, ...] = tuple()

    @classmethod
    def field_value_from_api_response(cls, field_name: str, field_type: type[F], val: Any) -> F:
        # A DocRef can have children that are themselves DocRefs. Currently readme.com only
        # supports one level of nesting, but this code will work for any depth.
        if field_name == "children":
            return cast(F, tuple(cls.from_api_response(x) for x in val))
        else:
            return super().field_value_from_api_response(field_name, field_type, val)

    def __str__(self):
        return (
            f"DocRef(id={self.id}, slug={self.slug}, title={self.title}, "
            f"order={self.order}, hidden={self.hidden})"
        )


@dataclass(frozen=True, slots=True)
class Doc(ReadmeEntity):
    """A full doc, including its body and other details."""

    slug: str
    title: str
    type: str
    version: str
    category: str
    hidden: bool
    body: str
    parentDoc: str = ""  # May be omitted in API responses if doc has no parent.

    def __str__(self):
        return (
            f"Doc(id={self.id}, category={self.category}, slug={self.slug}, "
            f"title={self.title}, body={self.body[:20]}...)"
        )


class ReadmeAPI:
    def __init__(self, api_key: str, version: str, url_prefix: str = _API_URL_PREFIX):
        self._api_key = api_key
        self._version = version
        self._url_prefix = url_prefix

    def get_categories(self) -> list[Category]:
        # https://docs.readme.com/reference/getcategories
        logger.info("Getting categories")
        return [Category.from_api_response(x) for x in cast(list, self._get("categories", ""))]

    def get_category(self, slug: str) -> Category:
        # https://docs.readme.com/reference/getcategory
        logger.info(f"Getting category {slug}")
        return Category.from_api_response(cast(dict, self._get(f"categories/{slug}", "")))

    def get_docs_for_category(self, slug: str) -> list[DocRef]:
        # https://docs.readme.com/reference/getcategorydocs
        logger.info(f"Getting docs for category {slug}")
        return [
            DocRef.from_api_response(x)
            for x in cast(list, self._get(f"categories/{slug}/docs", ""))
        ]

    def get_doc(self, slug: str) -> Doc:
        # https://docs.readme.com/reference/getdoc
        logger.info(f"Getting doc at slug {slug}")
        return Doc.from_api_response(cast(dict, self._get(f"docs/{slug}", "")))

    def create_doc(
        self,
        title: str,
        category: str,
        *,
        typ: str | None = None,
        body: str | None = None,
        hidden: bool | None = None,
        order: int | None = None,
        parentDoc: str | None = None,
    ) -> Doc:
        logger.info(f"Creating doc with title {title}")
        # https://docs.readme.com/reference/createdoc
        return self._create_or_update_doc(
            slug=None,
            title=title,
            category=category,
            typ=typ,
            body=body,
            hidden=hidden,
            order=order,
            parentDoc=parentDoc,
        )

    def update_doc(
        self,
        slug: str,
        title: str,
        category: str,
        *,
        typ: str | None = None,
        body: str | None = None,
        hidden: bool | None = None,
        order: int | None = None,
        parentDoc: str | None = None,
    ) -> Doc:
        # https://docs.readme.com/reference/updatedoc
        logger.info(f"Updating doc at slug {slug}")
        return self._create_or_update_doc(
            slug=slug,
            title=title,
            category=category,
            typ=typ,
            body=body,
            hidden=hidden,
            order=order,
            parentDoc=parentDoc,
        )

    def delete_doc(self, slug: str) -> None:
        # https://docs.readme.com/reference/deletedoc
        logger.info(f"Deleting doc at slug {slug}")
        self._delete(f"docs/{slug}", "")

    def _create_or_update_doc(
        self,
        *,
        slug: str | None,  # If None we create a doc, otherwise we update the doc at this slug.
        title: str,  # Required by the API.
        category: str,  # Required by the API.
        typ: str | None,  # If None, the API default of "basic" will apply.
        body: str | None,  # If None, the API default of "" will apply.
        hidden: bool | None,  # If None, the API default of True will apply.
        order: int | None,  # If None, the API default of 999 will apply.
        parentDoc: str | None,  # If None, the API default of "" will apply.
    ) -> Doc:
        fields = {
            "title": title,
            "type": typ,
            "body": body,
            "category": category,
            "hidden": hidden,
            "order": order,
            "parentDoc": parentDoc,
        }
        # We strip out fields that weren't provided as args, and rely on the API's defaults.
        specified_fields = {k: v for (k, v) in fields.items() if v is not None}
        payload = json.dumps(specified_fields)
        if slug:
            res = self._put(f"docs/{slug}", payload)
        else:
            res = self._post("docs/", payload)
        return Doc.from_api_response(cast(dict, res))

    def _get(self, endpoint: str, payload: str) -> ApiResponse:
        return self._request("GET", endpoint, payload)

    def _post(self, endpoint: str, payload: str) -> ApiResponse:
        return self._request("POST", endpoint, payload)

    def _put(self, endpoint: str, payload: str) -> ApiResponse:
        return self._request("PUT", endpoint, payload)

    def _delete(self, endpoint: str, payload: str) -> ApiResponse:
        return self._request("DELETE", endpoint, payload)

    def _request(self, method: str, endpoint: str, payload: str) -> ApiResponse:
        """Send a request to the readme.io API."""
        url = f"{self._url_prefix}{endpoint}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-readme-version": self._version,
        }
        logger.debug(f"Sending {method} request to {url}")
        logger.debug(f"  Payload: {payload}")
        response = requests.request(
            method, url, data=payload, headers=headers, auth=(self._api_key, "")
        )
        response.raise_for_status()
        return cast(ApiResponse, response.json()) if response.text else {}
