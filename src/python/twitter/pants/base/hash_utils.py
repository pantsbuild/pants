
import hashlib

def hash_all(strs):
  """Returns a hash of the concatenation of all the strings in strs."""
  sha = hashlib.sha1()
  for s in strs:
    sha.update(s)
  return sha.hexdigest()
