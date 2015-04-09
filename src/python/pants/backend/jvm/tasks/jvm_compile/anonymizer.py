# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import base64
import os
import random
import re


_default_keep_words = [
  'AAAAAAAAAAA=',
  'analysis',
  'anonfun',
  'apply',
  'beta',
  'class',
  'classes',
  'com',
  'd',
  'home',
  'jar',
  'jars',
  'java',
  'javac',
  'jvm',
  'lib',
  'library',
  'pants',
  'rt',
  'scala',
  'scalac',
  'src',
  'unapply',
  'users',
  'web'
]

_default_word_map = {
  'foursquare': 'acme',
  'benjy': 'kermit'
}

# TODO: Move somewhere more general? Could also be used to anonymize source files.

class TokenTranslator(object):
  """Processes tokens (typically from analysis files), mapping them to randomly chosen words.

  Subclasses determine what happens with those translations by implementing handle_conversion().
  """

  # Utility method for anonymizing base64-encoded binary data in analysis files.
  @staticmethod
  def _random_base64_string():
    n = random.randint(20, 200)
    return base64.b64encode(os.urandom(n))


  # Break on delimiters (digits, space, forward slash, dash, underscore, dollar, period) and on
  # upper-case letters.
  _DELIMITER = r'\d|\s|/|-|_|\$|\.'
  _UPPER = r'[A-Z]'
  _UPPER_CASE_RE = re.compile(r'^{}$'.format(_UPPER))
  _DELIMITER_RE = re.compile(r'^{}$'.format(_DELIMITER))
  _BREAK_ON_RE = re.compile(r'({}|{})'.format(_DELIMITER, _UPPER))  # Capture what we broke on.

  # Valid replacement words must be all lower-case ASCII letters, with no apostrophes etc, and must be
  # at least 5 characters.
  _WORD_RE = re.compile(r'^[a-z]{5}[a-z]*$')

  def __init__(self, word_list, word_map=None, keep=None, strict=False):
    self._translations = {}
    self._reverse_translations = {}
    self._word_map = _default_word_map if word_map is None else word_map
    self._keep = _default_keep_words if keep is None else keep

    # Init from args.
    for k, v in self._word_map.items():
      self._add_translation(k, v)
    for w in self._keep:
      self._add_translation(w, w)

    # Prepare list of candidate translations.
    self._unused_words = list(
      set(filter(TokenTranslator._WORD_RE.match, word_list)) -
      set(self._translations.values()) -
      set(self._translations.keys()))
    random.shuffle(self._unused_words)

    self._strict = strict

    # If we're not strict and we run out of replacement words, we count how many more words
    # we need, so we can give a useful error message to that effect.
    self._words_needed = 0

  def words_needed(self):
    return self._words_needed

  def check_for_comprehensiveness(self):
    if self._words_needed:
      raise Exception('Need {} more words in word_list for full anonymization.'.format(self._words_needed))

  def convert(self, s):
    parts = TokenTranslator._BREAK_ON_RE.split(s)
    parts_iter = iter(parts)
    converted_parts = []
    for part in parts_iter:
      if part == '' or TokenTranslator._DELIMITER_RE.match(part):
        converted_parts.append(part)
      elif TokenTranslator._UPPER_CASE_RE.match(part):
        # Join to the rest of the word, if any.
        token = part
        try:
          token += parts_iter.next()
        except StopIteration:
          pass
        converted_parts.append(self._convert_single_token(token))
      else:
        converted_parts.append(self._convert_single_token(part))
    return self.handle_conversion(s, ''.join(converted_parts))

  def convert_base64_string(self, s):
    translation = self._translations.get(s)
    if translation is None:
      translation = TokenTranslator._random_base64_string()
      self._add_translation(s, translation)
    return self.handle_conversion(s, translation)

  def handle_conversion(self, s, translation):
    """What the conversion functions should return when converting s -> translation."""
    raise NotImplementedError()

  def _convert_single_token(self, token):
    lower = token.lower()
    translation = self._translations.get(lower)
    if translation is None:
      if not self._unused_words:
        if self._strict:
          raise Exception('Ran out of words to translate to.')
        else:
          self._words_needed += 1
          translation = lower
      else:
        translation = self._unused_words.pop()
      self._add_translation(lower, translation)
    # Use the same capitalization as the original word.
    if token[0].isupper():
      return translation.capitalize()
    else:
      return translation

  def _add_translation(self, frm, to):
    if frm in self._translations:
      raise Exception('Word already has translation: {} -> {}'.format(frm, self._translations[frm]))
    if to in self._reverse_translations:
      raise Exception('Translation target already used: {} -> {}'.format(self._reverse_translations[to], to))
    self._translations[frm] = to
    self._reverse_translations[to] = frm


class TranslationCapturer(TokenTranslator):
  """Captures strings that need anonymizing, but doesn't actually anonymize them.

  Useful when we need the anonymized strings to be in the same dictionary order as the strings
  they replace: We capture all strings that need anonymizing in one pass, and then anonymize in a
  second pass.
  """
  def handle_conversion(self, s, translation):
    return s  # Return the original string.

  def get_order_preserving_anonymizer(self):
    """Returns an Anonymizer that preserves dictionary order.

    Must be run on the exact same sequence as this capturer.
    """
    # Look only at translations we generated, ignoring the ones passed in to our ctor.
    generated_translations = dict(self._translations)
    for k in self._word_map.keys():
      del generated_translations[k]
    for k in self._keep:
      del generated_translations[k]

    # Reassign keys to values so that dictionary order is preserved.
    sorted_keys = sorted(generated_translations.keys())
    sorted_values = sorted(generated_translations.values())
    ordered_translations = dict(zip(sorted_keys, sorted_values))

    # Add the preset translations back in.
    for k, v in self._word_map.items():
      ordered_translations[k] = v

    # This anonymizer should only be used on the exact same objects the capture was run on, and
    # it already contains translations for all those, so it needs no wordlist.
    return TokenTranslator([], ordered_translations, self._keep, self._strict)


class Anonymizer(TokenTranslator):
  """Anonymizes names in analysis files.

  Will replace all words in word_map with the corresponding value.

  Will replace all other words with a random word from word_list, except for
  words in keep.

  Replacements are 1:1, and therefore invertible.

  Useful for obfuscating real-life analysis files so we can use them in tests without
  leaking proprietary information.
  """
  def handle_conversion(self, s, translation):
    return translation
