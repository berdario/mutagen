# Copyright 2006 Joe Wreschnig
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.
#
# $Id: _util.py 4218 2007-12-02 06:11:20Z piman $

"""Utility classes for Mutagen.

You should not rely on the interfaces here being stable. They are
intended for internal use in Mutagen only.
"""

import sys
import struct
from functools import total_ordering, wraps
from zlib import decompress

from fnmatch import fnmatchcase

PY2 = sys.version_info[0] == 2

if PY2:
    text_type = unicode
    string_types = (unicode, str)
    byte_types = (str, bytearray)
    buffer = buffer
    exec("def reraise(tp, value, tb): raise tp, value, tb")

    @wraps(decompress)
    def zlib_decompress(string, *args, **kwargs):
        return bytearray(decompress(str(string), *args, **kwargs))
else:
    text_type = str
    string_types = (str, )
    byte_types = (bytes, bytearray)
    buffer = memoryview
    def reraise(tp, value, tb):
        raise tp(value).with_traceback(tb)

    @wraps(decompress)
    def zlib_decompress(string, *args, **kwargs):
        return bytearray(decompress(string, *args, **kwargs))


@total_ordering
class DictMixin(object):
    """Implement the dict API using keys() and __*item__ methods.

    Similar to UserDict.DictMixin, this takes a class that defines
    __getitem__, __setitem__, __delitem__, and keys(), and turns it
    into a full dict-like object.

    UserDict.DictMixin is not suitable for this purpose because it's
    an old-style class.

    This class is not optimized for very large dictionaries; many
    functions have linear memory requirements. I recommend you
    override some of these functions if speed is required.
    """

    def __iter__(self):
        return iter(list(self.keys()))

    def has_key(self, key):
        try: self[key]
        except KeyError: return False
        else: return True
    __contains__ = has_key

    iterkeys = lambda self: iter(list(self.keys()))

    def values(self):
        return list(map(self.__getitem__, list(self.keys())))
    itervalues = lambda self: iter(list(self.values()))

    def items(self):
        return list(zip(list(self.keys()), list(self.values())))
    iteritems = lambda s: iter(list(s.items()))

    def clear(self):
        list(map(self.__delitem__, list(self.keys())))

    def pop(self, key, *args):
        if len(args) > 1:
            raise TypeError("pop takes at most two arguments")
        try: value = self[key]
        except KeyError:
            if args: return args[0]
            else: raise
        del(self[key])
        return value

    def popitem(self):
        try:
            key = list(self.keys())[0]
            return key, self.pop(key)
        except IndexError: raise KeyError("dictionary is empty")

    def update(self, other=None, **kwargs):
        if other is None:
            self.update(kwargs)
            other = {}

        try: list(map(self.__setitem__, list(other.keys()), list(other.values())))
        except AttributeError:
            for key, value in other:
                self[key] = value

    def setdefault(self, key, default=None):
        try: return self[key]
        except KeyError:
            self[key] = default
            return default

    def get(self, key, default=None):
        try: return self[key]
        except KeyError: return default

    def __repr__(self):
        return repr(dict(list(self.items())))

    def __eq__(self, other):
        return {k:v for k,v in self.items()} == other

    def __lt__(self, other):
        return {k:v for k,v in self.items()} < other

    __hash__ = object.__hash__

    def __len__(self):
        return len(list(self.keys()))

class DictProxy(DictMixin):
    def __init__(self, *args, **kwargs):
        self.__dict = {}
        super(DictProxy, self).__init__(*args, **kwargs)

    def __getitem__(self, key):
        return self.__dict[key]

    def __setitem__(self, key, value):
        self.__dict[key] = value

    def __delitem__(self, key):
        del(self.__dict[key])

    def keys(self):
        return list(self.__dict.keys())

def struct_unpack(fmt, buf):
    return struct.unpack(fmt.encode(), buf)

def struct_pack(fmt, *args):
    return struct.pack(fmt.encode(), *args)

def struct_calcsize(fmt):
    return struct.calcsize(fmt.encode())

class cdata(object):
    """C character buffer to Python numeric type conversions."""

    from struct import error

    short_le = staticmethod(lambda data: struct_unpack('<h', data)[0])
    ushort_le = staticmethod(lambda data: struct_unpack('<H', data)[0])

    short_be = staticmethod(lambda data: struct_unpack('>h', data)[0])
    ushort_be = staticmethod(lambda data: struct_unpack('>H', data)[0])

    int_le = staticmethod(lambda data: struct_unpack('<i', data)[0])
    uint_le = staticmethod(lambda data: struct_unpack('<I', data)[0])

    int_be = staticmethod(lambda data: struct_unpack('>i', data)[0])
    uint_be = staticmethod(lambda data: struct_unpack('>I', data)[0])

    longlong_le = staticmethod(lambda data: struct_unpack('<q', data)[0])
    ulonglong_le = staticmethod(lambda data: struct_unpack('<Q', data)[0])

    longlong_be = staticmethod(lambda data: struct_unpack('>q', data)[0])
    ulonglong_be = staticmethod(lambda data: struct_unpack('>Q', data)[0])

    to_short_le = staticmethod(lambda data: struct_pack('<h', data))
    to_ushort_le = staticmethod(lambda data: struct_pack('<H', data))

    to_short_be = staticmethod(lambda data: struct_pack('>h', data))
    to_ushort_be = staticmethod(lambda data: struct_pack('>H', data))

    to_int_le = staticmethod(lambda data: struct_pack('<i', data))
    to_uint_le = staticmethod(lambda data: struct_pack('<I', data))

    to_int_be = staticmethod(lambda data: struct_pack('>i', data))
    to_uint_be = staticmethod(lambda data: struct_pack('>I', data))

    to_longlong_le = staticmethod(lambda data: struct_pack('<q', data))
    to_ulonglong_le = staticmethod(lambda data: struct_pack('<Q', data))

    to_longlong_be = staticmethod(lambda data: struct_pack('>q', data))
    to_ulonglong_be = staticmethod(lambda data: struct_pack('>Q', data))

    bitswap = bytearray(sum([((val >> i) & 1) << (7-i) for i in range(8)]) for val in range(256))

    test_bit = staticmethod(lambda value, n: bool((value >> n) & 1))

def lock(fileobj):
    """Lock a file object 'safely'.

    That means a failure to lock because the platform doesn't
    support fcntl or filesystem locks is not considered a
    failure. This call does block.

    Returns whether or not the lock was successful, or
    raises an exception in more extreme circumstances (full
    lock table, invalid file).
    """
    try: import fcntl
    except ImportError:
        return False
    else:
        try: fcntl.lockf(fileobj, fcntl.LOCK_EX)
        except IOError:
            # FIXME: There's possibly a lot of complicated
            # logic that needs to go here in case the IOError
            # is EACCES or EAGAIN.
            return False
        else:
            return True

def unlock(fileobj):
    """Unlock a file object.

    Don't call this on a file object unless a call to lock()
    returned true.
    """
    # If this fails there's a mismatched lock/unlock pair,
    # so we definitely don't want to ignore errors.
    import fcntl
    fcntl.lockf(fileobj, fcntl.LOCK_UN)

def insert_bytes(fobj, size, offset, BUFFER_SIZE=2**16):
    """Insert size bytes of empty space starting at offset.

    fobj must be an open file object, open rb+ or
    equivalent. Mutagen tries to use mmap to resize the file, but
    falls back to a significantly slower method if mmap fails.
    """
    assert 0 < size
    assert 0 <= offset
    locked = False
    fobj.seek(0, 2)
    filesize = fobj.tell()
    movesize = filesize - offset
    fobj.write(b'\x00' * size)
    fobj.flush()
    try:
        try:
            import mmap
            memmap = mmap.mmap(fobj.fileno(), filesize + size)
            try:
                memmap.move(offset + size, offset, movesize)
            finally:
                memmap.close()
        except (ValueError, EnvironmentError, ImportError):
            # handle broken mmap scenarios
            locked = lock(fobj)
            fobj.truncate(filesize)

            fobj.seek(0, 2)
            padsize = size
            # Don't generate an enormous string if we need to pad
            # the file out several megs.
            while padsize:
                addsize = min(BUFFER_SIZE, padsize)
                fobj.write(b"\x00" * addsize)
                padsize -= addsize

            fobj.seek(filesize, 0)
            while movesize:
                # At the start of this loop, fobj is pointing at the end
                # of the data we need to move, which is of movesize length.
                thismove = min(BUFFER_SIZE, movesize)
                # Seek back however much we're going to read this frame.
                fobj.seek(-thismove, 1)
                nextpos = fobj.tell()
                # Read it, so we're back at the end.
                data = fobj.read(thismove)
                # Seek back to where we need to write it.
                fobj.seek(-thismove + size, 1)
                # Write it.
                fobj.write(data)
                # And seek back to the end of the unmoved data.
                fobj.seek(nextpos)
                movesize -= thismove

            fobj.flush()
    finally:
        if locked:
            unlock(fobj)

def delete_bytes(fobj, size, offset, BUFFER_SIZE=2**16):
    """Delete size bytes of empty space starting at offset.

    fobj must be an open file object, open rb+ or
    equivalent. Mutagen tries to use mmap to resize the file, but
    falls back to a significantly slower method if mmap fails.
    """
    locked = False
    assert 0 < size
    assert 0 <= offset
    fobj.seek(0, 2)
    filesize = fobj.tell()
    movesize = filesize - offset - size
    assert 0 <= movesize
    try:
        if movesize > 0:
            fobj.flush()
            try:
                import mmap
                memmap = mmap.mmap(fobj.fileno(), filesize)
                try: memmap.move(offset, offset + size, movesize)
                finally: memmap.close()
            except (ValueError, EnvironmentError, ImportError):
                # handle broken mmap scenarios
                locked = lock(fobj)
                fobj.seek(offset + size)
                buf = fobj.read(BUFFER_SIZE)
                while buf:
                    fobj.seek(offset)
                    fobj.write(buf)
                    offset += len(buf)
                    fobj.seek(offset + size)
                    buf = fobj.read(BUFFER_SIZE)
        fobj.truncate(filesize - size)
        fobj.flush()
    finally:
        if locked:
            unlock(fobj)

def utf8(data):
    """Convert a basestring to a valid UTF-8 str."""
    if isinstance(data, byte_types):
        return bytearray(data.decode("utf-8", "replace").encode("utf-8"))
    elif isinstance(data, text_type):
        return bytearray(data.encode("utf-8"))
    else: raise TypeError("only unicode/str types can be converted to UTF-8")

def dict_match(d, key, default=None):
    try:
        return d[key]
    except KeyError:
        for pattern, value in d.items():
            if fnmatchcase(key, pattern):
                return value
    return default


_type = type
def type(cls, superclass=None, data=None):
    if superclass is not None and data is not None:
        if PY2 and isinstance(cls, unicode):
            cls = cls.encode('ascii')
        return _type(cls, superclass, data)
    elif not (superclass is None and data is None):
        raise TypeError("type() takes 1 or 3 arguments")
    else:
        return _type(cls)

