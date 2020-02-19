# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from unittest.mock import Mock, patch

import requests

from pants.cache.resolver import Resolver, ResponseParser, RESTfulResolver

PATCH_OPTS = dict(autospec=True, spec_set=True)


class TestResponseParser(unittest.TestCase):
    def testParse(self):
        response_parser = ResponseParser()
        self.assertEqual(["url1", "url2"], response_parser.parse(b'{"hostlist": ["url1", "url2"]}'))

        self.assertEqual([], response_parser.parse(b'{"hostlist": []}'))

        with self.assertRaises(ResponseParser.ResponseParserError):
            response_parser.parse(b'{"hostlist": "not a list"}')

        with self.assertRaises(ResponseParser.ResponseParserError):
            response_parser.parse(b"a garbage response")

        with self.assertRaises(ResponseParser.ResponseParserError):
            response_parser.parse(b'{"mismatched-index": ["url1", "url2"]}')

        with self.assertRaises(ResponseParser.ResponseParserError):
            # a mismatched encoding also fails
            response_parser.parse('{"hostlist": ["url1", "url2"]}'.encode("utf-16"))


class TestRESTfulResolver(unittest.TestCase):

    TEST_TIMEOUT = 1
    TEST_RETRIES = 3

    RESOLVED_URL_1 = "http://10.0.0.1:1"
    RESOLVED_URL_2 = "http://10.0.0.2:2"
    URLS = [RESOLVED_URL_1, RESOLVED_URL_2]

    TEST_RESOLVED_FROM = "http://test-resolver"

    TEST_REQUEST_EXCEPTION = requests.exceptions.ConnectionError()

    def setUp(self):
        self.parser = Mock(spec=ResponseParser)
        self.resolver = RESTfulResolver(self.TEST_TIMEOUT, self.TEST_RETRIES, self.parser)

    def mock_response(self, status_code, urls=None):
        response = Mock()
        response.status_code = status_code
        self.parser.parse = Mock(return_value=urls)
        return response

    def testResolveSuccess(self):
        with patch.object(requests.Session, "get", **PATCH_OPTS) as mock_get:
            mock_get.return_value = self.mock_response(requests.codes.ok, urls=self.URLS)
            self.assertEqual(self.URLS, self.resolver.resolve(self.TEST_RESOLVED_FROM))

    def testResolveErrorEmptyReturn(self):
        with patch.object(requests.Session, "get", **PATCH_OPTS) as mock_get:
            mock_get.return_value = self.mock_response(requests.codes.ok, urls=[])
            with self.assertRaises(Resolver.ResolverError):
                self.resolver.resolve(self.TEST_RESOLVED_FROM)

    def testResolveParseError(self):
        with patch.object(requests.Session, "get", **PATCH_OPTS) as mock_get:
            mock_get.return_value = self.mock_response(
                requests.codes.ok, urls="this is a garbage string"
            )
            self.parser.parse.side_effect = ResponseParser.ResponseParserError()
            with self.assertRaises(Resolver.ResolverError):
                self.resolver.resolve(self.TEST_RESOLVED_FROM)

    def testResolveResponseError(self):
        with patch.object(requests.Session, "get", **PATCH_OPTS) as mock_get:
            mock_get.return_value = self.mock_response(requests.codes.service_unavailable)
            with self.assertRaises(Resolver.ResolverError):
                self.resolver.resolve(self.TEST_RESOLVED_FROM)

    def testResolveConnectionError(self):
        with patch.object(requests.Session, "get", **PATCH_OPTS) as mock_get:
            mock_get.side_effect = self.TEST_REQUEST_EXCEPTION
            with self.assertRaises(Resolver.ResolverError):
                self.resolver.resolve(self.TEST_RESOLVED_FROM)
