# An APEv2 tag reader
#
# Copyright 2005 Joe Wreschnig
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.
#
# $Id: apev2.py 4008 2007-04-21 04:02:07Z piman $

"""APEv2 reading and writing.

The APEv2 format is most commonly used with Musepack files, but is
also the format of choice for WavPack and other formats. Some MP3s
also have APEv2 tags, but this can cause problems with many MP3
decoders and taggers.

APEv2 tags, like Vorbis comments, are freeform key=value pairs. APEv2
keys can be any ASCII string with characters from 0x20 to 0x7E,
between 2 and 255 characters long.  Keys are case-sensitive, but
readers are recommended to be case insensitive, and it is forbidden to
multiple keys which differ only in case.  Keys are usually stored
title-cased (e.g. 'Artist' rather than 'artist').

APEv2 values are slightly more structured than Vorbis comments; values
are flagged as one of text, binary, or an external reference (usually
a URI).

Based off the format specification found at
http://wiki.hydrogenaudio.org/index.php?title=APEv2_specification.
"""

__all__ = ["APEv2", "APEv2File", "Open", "delete"]

from io import BytesIO
from functools import total_ordering

from mutagen._util import struct_pack, utf8, text_type

def is_valid_apev2_key(key):
    key = utf8(key)
    return (2 <= len(key) <= 255 and min(key) >= ord(' ') and max(key) <= ord('~') and
            key not in [b"OggS", b"TAG", b"ID3", b"MP+"])

# There are three different kinds of APE tag values.
# "0: Item contains text information coded in UTF-8
#  1: Item contains binary information
#  2: Item is a locator of external stored information [e.g. URL]
#  3: reserved"
TEXT, BINARY, EXTERNAL = list(range(3))

HAS_HEADER = 1 << 31
HAS_NO_FOOTER = 1 << 30
IS_HEADER  = 1 << 29

class error(IOError): pass
class APENoHeaderError(error, ValueError): pass
class APEUnsupportedVersionError(error, ValueError): pass
class APEBadItemError(error, ValueError): pass

from mutagen import Metadata, FileType
from mutagen._util import DictMixin, cdata, utf8, delete_bytes

class _APEv2Data(object):
    # Store offsets of the important parts of the file.
    start = header = data = footer = end = None
    # Footer or header; seek here and read 32 to get version/size/items/flags
    metadata = None
    # Actual tag data
    tag = None

    version = None
    size = None
    items = None
    flags = 0

    # The tag is at the start rather than the end. A tag at both
    # the start and end of the file (i.e. the tag is the whole file)
    # is not considered to be at the start.
    is_at_start = False

    def __init__(self, fileobj):
        self.__find_metadata(fileobj)
        if self.header is None and self.footer is None: return
        self.metadata = max(filter(lambda x: x is not None, (self.header, self.footer)))
        self.__fill_missing(fileobj)
        self.__fix_brokenness(fileobj)
        if self.data is not None:
            fileobj.seek(self.data)
            self.tag = fileobj.read(self.size)

    def __find_metadata(self, fileobj):
        # Try to find a header or footer.

        # Check for a simple footer.
        try: fileobj.seek(-32, 2)
        except IOError:
            fileobj.seek(0, 2)
            return
        if fileobj.read(8) == b"APETAGEX":
            fileobj.seek(-8, 1)
            self.footer = self.metadata = fileobj.tell()
            return

        # Check for an APEv2 tag followed by an ID3v1 tag at the end.
        try:
            fileobj.seek(-128, 2)
            if fileobj.read(3) == b"TAG":

                fileobj.seek(-35, 1) # "TAG" + header length
                if fileobj.read(8) == b"APETAGEX":
                    fileobj.seek(-8, 1)
                    self.footer = fileobj.tell()
                    return

                # ID3v1 tag at the end, maybe preceded by Lyrics3v2.
                # (http://www.id3.org/lyrics3200.html)
                # (header length - "APETAGEX") - "LYRICS200"
                fileobj.seek(15, 1)
                if fileobj.read(9) == b'LYRICS200':
                    fileobj.seek(-15, 1) # "LYRICS200" + size tag
                    try: offset = int(fileobj.read(6))
                    except ValueError:
                        raise IOError

                    fileobj.seek(-32 - offset - 6, 1)
                    if fileobj.read(8) == b"APETAGEX":
                        fileobj.seek(-8, 1)
                        self.footer = fileobj.tell()
                        return

        except IOError:
            pass

        # Check for a tag at the start.
        fileobj.seek(0, 0)
        if fileobj.read(8) == b"APETAGEX":
            self.is_at_start = True
            self.header = 0

    def __fill_missing(self, fileobj):
        fileobj.seek(self.metadata + 8)
        self.version = fileobj.read(4)
        self.size = cdata.uint_le(fileobj.read(4))
        self.items = cdata.uint_le(fileobj.read(4))
        self.flags = cdata.uint_le(fileobj.read(4))

        if self.header is not None:
            self.data = self.header + 32
            # If we're reading the header, the size is the header
            # offset + the size, which includes the footer.
            self.end = self.data + self.size
            fileobj.seek(self.end - 32, 0)
            if fileobj.read(8) == b"APETAGEX":
                self.footer = self.end - 32
        elif self.footer is not None:
            self.end = self.footer + 32
            self.data = self.end - self.size
            if self.flags & HAS_HEADER:
                self.header = self.data - 32
            else:
                self.header = self.data
        else: raise APENoHeaderError("No APE tag found")

    def __fix_brokenness(self, fileobj):
        # Fix broken tags written with PyMusepack.
        if self.header is not None: start = self.header
        else: start = self.data
        fileobj.seek(start)

        while start > 0:
            # Clean up broken writing from pre-Mutagen PyMusepack.
            # It didn't remove the first 24 bytes of header.
            try: fileobj.seek(-24, 1)
            except IOError:
                break
            else:
                if fileobj.read(8) == b"APETAGEX":
                    fileobj.seek(-8, 1)
                    start = fileobj.tell()
                else: break
        self.start = start

class APEv2(DictMixin, Metadata):
    """A file with an APEv2 tag.

    ID3v1 tags are silently ignored and overwritten.
    """

    filename = None

    def __init__(self, *args, **kwargs):
        self.__casemap = {}
        self.__dict = {}
        super(APEv2, self).__init__(*args, **kwargs)
        # Internally all names are stored as lowercase, but the case
        # they were set with is remembered and used when saving.  This
        # is roughly in line with the standard, which says that keys
        # are case-sensitive but two keys differing only in case are
        # not allowed, and recommends case-insensitive
        # implementations.

    def pprint(self):
        """Return tag key=value pairs in a human-readable format."""
        items = sorted(list(self.items()))
        return "\n".join(["%s=%s" % (k, v.pprint()) for k, v in items])

    def load(self, filename):
        """Load tags from a filename."""
        self.filename = filename
        fileobj = open(filename, "rb")
        try:
            data = _APEv2Data(fileobj)
        finally:
            fileobj.close()
        if data.tag:
            self.clear()
            self.__casemap.clear()
            self.__parse_tag(data.tag, data.items)
        else:
            raise APENoHeaderError("No APE tag found")

    def __parse_tag(self, tag, count):
        fileobj = BytesIO(tag)

        for i in range(count):
            size = cdata.uint_le(fileobj.read(4))
            flags = cdata.uint_le(fileobj.read(4))

            # Bits 1 and 2 bits are flags, 0-3
            # Bit 0 is read/write flag, ignored
            kind = (flags & 6) >> 1
            if kind == 3:
                raise APEBadItemError("value type must be 0, 1, or 2")
            key = value = fileobj.read(1)
            while key[-1:] != b'\x00' and value:
                value = fileobj.read(1)
                key += value
            if key[-1:] == b"\x00":
                key = key[:-1]
            value = fileobj.read(size)
            self[key.decode()] = APEValue(value, kind)

    def __getitem__(self, key):
        if not is_valid_apev2_key(key):
            raise KeyError("%r is not a valid APEv2 key" % key)
        return self.__dict[key.lower()]

    def __delitem__(self, key):
        if not is_valid_apev2_key(key):
            raise KeyError("%r is not a valid APEv2 key" % key)
        del(self.__dict[key.lower()])

    def __setitem__(self, key, value):
        """'Magic' value setter.

        This function tries to guess at what kind of value you want to
        store. If you pass in a valid UTF-8 or Unicode string, it
        treats it as a text value. If you pass in a list, it treats it
        as a list of string/Unicode values.  If you pass in a string
        that is not valid UTF-8, it assumes it is a binary value.

        If you need to force a specific type of value (e.g. binary
        data that also happens to be valid UTF-8, or an external
        reference), use the APEValue factory and set the value to the
        result of that:
            from mutagen.apev2 import APEValue, EXTERNAL
            tag['Website'] = APEValue('http://example.org', EXTERNAL)
        """

        if not is_valid_apev2_key(key):
            raise KeyError("%r is not a valid APEv2 key" % key)

        if not isinstance(value, _APEValue):
            # let's guess at the content if we're not already a value...
            if isinstance(value, text_type):
                # unicode? we've got to be text.
                value = APEValue(utf8(value), TEXT)
            elif isinstance(value, list):
                # list? text.
                value = APEValue(bytearray([0]).join(map(utf8, value)), TEXT)
            else:
                try: value.decode("utf-8")
                except UnicodeError:
                    # invalid UTF8 text, probably binary
                    value = APEValue(value, BINARY)
                else:
                    # valid UTF8, probably text
                    value = APEValue(utf8(value), TEXT)
        self.__casemap[key.lower()] = key
        self.__dict[key.lower()] = value

    def keys(self):
        return [self.__casemap.get(key, key) for key in list(self.__dict.keys())]

    def save(self, filename=None):
        """Save changes to a file.

        If no filename is given, the one most recently loaded is used.

        Tags are always written at the end of the file, and include
        a header and a footer.
        """

        filename = filename or self.filename
        try:
            fileobj = open(filename, "r+b")
        except IOError:
            fileobj = open(filename, "w+b")
        data = _APEv2Data(fileobj)

        if data.is_at_start:
            delete_bytes(fileobj, data.end - data.start, data.start)
        elif data.start is not None:
            fileobj.seek(data.start)
            # Delete an ID3v1 tag if present, too.
            fileobj.truncate()
        fileobj.seek(0, 2)

        # "APE tags items should be sorted ascending by size... This is
        # not a MUST, but STRONGLY recommended. Actually the items should
        # be sorted by importance/byte, but this is not feasible."
        tags = sorted((v._internal(k) for k, v in list(self.items())), key=len)
        num_tags = len(tags)
        tags = bytearray().join(tags)

        # tag string, version, tag size, item count, flags
        header = struct_pack("<8s 4I 8x", b"APETAGEX", 2000, len(tags)+32,
                             num_tags, HAS_HEADER|IS_HEADER)
        fileobj.write(header)

        fileobj.write(tags)

        # tag string, version, tag size, item count, flags
        footer = struct_pack("<8s 4I 8x", b"APETAGEX", 2000, len(tags) + 32,
                             num_tags, HAS_HEADER)
        fileobj.write(footer)
        fileobj.close()

    def delete(self, filename=None):
        """Remove tags from a file."""
        filename = filename or self.filename
        fileobj = open(filename, "r+b")
        try:
            data = _APEv2Data(fileobj)
            if data.start is not None and data.size is not None:
                delete_bytes(fileobj, data.end - data.start, data.start)
        finally:
            fileobj.close()
        self.clear()

Open = APEv2

def delete(filename):
    """Remove tags from a file."""
    try: APEv2(filename).delete()
    except APENoHeaderError: pass

def APEValue(value, kind):
    """APEv2 tag value factory.

    Use this if you need to specify the value's type manually.  Binary
    and text data are automatically detected by APEv2.__setitem__.
    """
    if kind == TEXT: return APETextValue(value, kind)
    elif kind == BINARY: return APEBinaryValue(value, kind)
    elif kind == EXTERNAL: return APEExtValue(value, kind)
    else: raise ValueError("kind must be TEXT, BINARY, or EXTERNAL")

class _APEValue(object):
    def __init__(self, value, kind):
        self.kind = kind
        self.value = value

    def __len__(self):
        return len(self.value)
    def __str__(self):
        return self.value

    # Packed format for an item:
    # 4B: Value length
    # 4B: Value type
    # Key name
    # 1B: Null
    # Key value
    def _internal(self, key):
        if isinstance(key, text_type):
            key = key.encode('utf-8')
        return struct_pack("<2I", len(self.value), self.kind << 1) + \
            key + b"\0" + self.value

    def __repr__(self):
        return "%s(%r, %d)" % (type(self).__name__, self.value, self.kind)

@total_ordering
class APETextValue(_APEValue):
    """An APEv2 text value.

    Text values are Unicode/UTF-8 strings. They can be accessed like
    strings (with a null seperating the values), or arrays of strings."""

    def __str__(self):
        return self.value.decode()

    def __iter__(self):
        """Iterate over the strings of the value (not the characters)"""
        return iter(str(self).split("\0"))

    def __getitem__(self, index):
        return str(self).split("\0")[index]

    def __len__(self):
        return self.value.count(b"\0") + 1

    def __eq__(self, other):
        return str(self) == other
        
    def __lt__(self, other):
        return str(self) < other

    __hash__ = _APEValue.__hash__

    def __setitem__(self, index, value):
        values = list(self)
        values[index] = value
        self.value = "\0".join(values).encode()

    def pprint(self):
        return " / ".join(self)

class APEBinaryValue(_APEValue):
    """An APEv2 binary value."""

    def pprint(self): return "[%d bytes]" % len(self)

class APEExtValue(_APEValue):
    """An APEv2 external value.

    External values are usually URI or IRI strings.
    """
    def pprint(self): return "[External] %s" % str(self)

class APEv2File(FileType):
    class _Info(object):
        length = 0
        bitrate = 0
        def __init__(self, fileobj): pass
        pprint = staticmethod(lambda: "Unknown format with APEv2 tag.")

    def load(self, filename):
        self.filename = filename
        self.info = self._Info(open(filename, "rb"))
        try: self.tags = APEv2(filename)
        except error: self.tags = None

    def add_tags(self):
        if self.tags is None:
            self.tags = APEv2()
        else:
            raise ValueError("%r already has tags: %r" % (self, self.tags))

    def score(filename, fileobj, header):
        try: fileobj.seek(-160, 2)
        except IOError:
            fileobj.seek(0)
        footer = fileobj.read()
        filename = filename.lower()
        return ((b"APETAGEX" in footer) - header.startswith(b"ID3"))
    score = staticmethod(score)
