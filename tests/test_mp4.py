from __future__ import print_function
import os
import shutil

from io import BytesIO
from tempfile import mkstemp
from tests import TestCase, add
from mutagen.mp4 import MP4, Atom, Atoms, MP4Tags, MP4Info, \
     delete, MP4Cover, MP4MetadataError
from mutagen._util import cdata, struct_unpack
try: from os.path import devnull
except ImportError: devnull = "/dev/null"

class TAtom(TestCase):
    uses_mmap = False

    def test_no_children(self):
        fileobj = BytesIO(b"\x00\x00\x00\x08atom")
        atom = Atom(fileobj)
        self.failUnlessRaises(KeyError, atom.__getitem__, "test")

    def test_length_1(self):
        fileobj = BytesIO(b"\x00\x00\x00\x01atom"
                           b"\x00\x00\x00\x00\x00\x00\x00\x08" + b"\x00" * 8)
        self.failUnlessEqual(Atom(fileobj).length, 8)

    def test_render_too_big(self):
        class TooBig(bytes):
            def __len__(self):
                return 1 << 32
        data = TooBig(b"test")
        try: len(data)
        except OverflowError:
            # Py_ssize_t is still only 32 bits on this system.
            self.failUnlessRaises(OverflowError, Atom.render, "data", data)
        else:
            data = Atom.render("data", data)
            self.failUnlessEqual(len(data), 4 + 4 + 8 + 4)

    def test_length_0(self):
        fileobj = BytesIO(b"\x00\x00\x00\x00atom")
        Atom(fileobj)
        self.failUnlessEqual(fileobj.tell(), 8)
add(TAtom)

class TAtoms(TestCase):
    uses_mmap = False
    filename = os.path.join("tests", "data", "has-tags.m4a")

    def setUp(self):
        self.atoms = Atoms(open(self.filename, "rb"))

    def test___contains__(self):
        self.failUnless(self.atoms["moov"])
        self.failUnless(self.atoms["moov.udta"])
        self.failUnlessRaises(KeyError, self.atoms.__getitem__, "whee")

    def test_name(self):
        self.failUnlessEqual(self.atoms.atoms[0].name, b"ftyp")

    def test_children(self):
        self.failUnless(self.atoms.atoms[2].children)

    def test_no_children(self):
        self.failUnless(self.atoms.atoms[0].children is None)

    def test_extra_trailing_data(self):
        data = BytesIO(Atom.render("data", b"whee") + b"\x00\x00")
        self.failUnless(Atoms(data))

    def test_repr(self):
        repr(self.atoms)
add(TAtoms)

class TMP4Info(TestCase):
    uses_mmap = False

    def test_no_soun(self):
        self.failUnlessRaises(
            IOError, self.test_mdhd_version_1, "vide")

    def test_mdhd_version_1(self, soun="soun"):
        mdhd = Atom.render("mdhd", (b"\x01\x00\x00\x00" + b"\x00" * 16 +
                                    b"\x00\x00\x00\x02" + # 2 Hz
                                    b"\x00\x00\x00\x00\x00\x00\x00\x10"))
        hdlr = Atom.render("hdlr", b"\x00" * 8 + soun.encode())
        mdia = Atom.render("mdia", mdhd + hdlr)
        trak = Atom.render("trak", mdia)
        moov = Atom.render("moov", trak)
        fileobj = BytesIO(moov)
        atoms = Atoms(fileobj)
        info = MP4Info(atoms, fileobj)
        self.failUnlessEqual(info.length, 8)

    def test_multiple_tracks(self):
        hdlr = Atom.render("hdlr", b"\x00" * 8 + b"whee")
        mdia = Atom.render("mdia", hdlr)
        trak1 = Atom.render("trak", mdia)
        mdhd = Atom.render("mdhd", (b"\x01\x00\x00\x00" + b"\x00" * 16 +
                                    b"\x00\x00\x00\x02" + # 2 Hz
                                    b"\x00\x00\x00\x00\x00\x00\x00\x10"))
        hdlr = Atom.render("hdlr", b"\x00" * 8 + b"soun")
        mdia = Atom.render("mdia", mdhd + hdlr)
        trak2 = Atom.render("trak", mdia)
        moov = Atom.render("moov", trak1 + trak2)
        fileobj = BytesIO(moov)
        atoms = Atoms(fileobj)
        info = MP4Info(atoms, fileobj)
        self.failUnlessEqual(info.length, 8)
add(TMP4Info)

class TMP4Tags(TestCase):
    uses_mmap = False

    def wrap_ilst(self, data):
        ilst = Atom.render("ilst", data)
        meta = Atom.render("meta", b"\x00" * 4 + ilst)
        data = Atom.render("moov", Atom.render("udta", meta))
        fileobj = BytesIO(data)
        return MP4Tags(Atoms(fileobj), fileobj)

    def test_genre(self):
        data = Atom.render("data", b"\x00" * 8 + b"\x00\x01")
        genre = Atom.render("gnre", data)
        tags = self.wrap_ilst(genre)
        self.failIf("gnre" in tags)
        self.failUnlessEqual(tags[b"\xa9gen"], ["Blues"])

    def test_empty_cpil(self):
        cpil = Atom.render("cpil", Atom.render("data", b"\x00" * 8))
        tags = self.wrap_ilst(cpil)
        self.failUnless(b"cpil" in tags)
        self.failIf(tags[b"cpil"])

    def test_genre_too_big(self):
        data = Atom.render("data", b"\x00" * 8 + b"\x01\x00")
        genre = Atom.render("gnre", data)
        tags = self.wrap_ilst(genre)
        self.failIf("gnre" in tags)
        self.failIf(b"\xa9gen" in tags)

    def test_strips_unknown_types(self):
        data = Atom.render("data", b"\x00" * 8 + b"whee")
        foob = Atom.render("foob", data)
        tags = self.wrap_ilst(foob)
        self.failIf(tags)

    def test_bad_covr(self):
        data = Atom.render("foob", b"\x00\x00\x00\x0E" + b"\x00" * 4 + b"whee")
        covr = Atom.render("covr", data)
        self.failUnlessRaises(MP4MetadataError, self.wrap_ilst, covr)

    def test_covr_blank_format(self):
        data = Atom.render("data", b"\x00\x00\x00\x00" + b"\x00" * 4 + b"whee")
        covr = Atom.render("covr", data)
        tags = self.wrap_ilst(covr)
        self.failUnlessEqual(MP4Cover.FORMAT_JPEG, tags[b"covr"][0].imageformat)

    def test_render_bool(self):
        self.failUnlessEqual(MP4Tags()._MP4Tags__render_bool('pgap', True),
                             b"\x00\x00\x00\x19pgap\x00\x00\x00\x11data"
                             b"\x00\x00\x00\x15\x00\x00\x00\x00\x01")
        self.failUnlessEqual(MP4Tags()._MP4Tags__render_bool('pgap', False),
                             b"\x00\x00\x00\x19pgap\x00\x00\x00\x11data"
                             b"\x00\x00\x00\x15\x00\x00\x00\x00\x00")

    def test_render_text(self):
        self.failUnlessEqual(
             MP4Tags()._MP4Tags__render_text('purl', ['http://foo/bar.xml'], 0),
             b"\x00\x00\x00*purl\x00\x00\x00\"data\x00\x00\x00\x00\x00\x00"
             b"\x00\x00http://foo/bar.xml")
        self.failUnlessEqual(
             MP4Tags()._MP4Tags__render_text('aART', [u'\u0041lbum Artist']),
             b"\x00\x00\x00$aART\x00\x00\x00\x1cdata\x00\x00\x00\x01\x00\x00"
             b"\x00\x00\x41lbum Artist")
        self.failUnlessEqual(
             MP4Tags()._MP4Tags__render_text('aART', ['Album Artist', 'Whee']),
             b"\x00\x00\x008aART\x00\x00\x00\x1cdata\x00\x00\x00\x01\x00\x00"
             b"\x00\x00Album Artist\x00\x00\x00\x14data\x00\x00\x00\x01\x00"
             b"\x00\x00\x00Whee")
        
    def test_render_data(self):
        self.failUnlessEqual(
             MP4Tags()._MP4Tags__render_data('aART', 1, [b'whee']),
             b"\x00\x00\x00\x1caART"
             b"\x00\x00\x00\x14data\x00\x00\x00\x01\x00\x00\x00\x00whee")
        self.failUnlessEqual(
             MP4Tags()._MP4Tags__render_data('aART', 2, [b'whee', b'wee']),
             b"\x00\x00\x00/aART"
             b"\x00\x00\x00\x14data\x00\x00\x00\x02\x00\x00\x00\x00whee"
             b"\x00\x00\x00\x13data\x00\x00\x00\x02\x00\x00\x00\x00wee")

    def test_bad_text_data(self):
        data = Atom.render("datA", b"\x00\x00\x00\x01\x00\x00\x00\x00whee")
        data = Atom.render("aART", data)
        self.failUnlessRaises(MP4MetadataError, self.wrap_ilst, data)

    def test_render_freeform(self):
        self.failUnlessEqual(
             MP4Tags()._MP4Tags__render_freeform(
             '----:net.sacredchao.Mutagen:test', [b'whee', b'wee']),
             b"\x00\x00\x00a----"
             b"\x00\x00\x00\"mean\x00\x00\x00\x00net.sacredchao.Mutagen"
             b"\x00\x00\x00\x10name\x00\x00\x00\x00test"
             b"\x00\x00\x00\x14data\x00\x00\x00\x01\x00\x00\x00\x00whee"
             b"\x00\x00\x00\x13data\x00\x00\x00\x01\x00\x00\x00\x00wee")

    def test_bad_freeform(self):
        mean = Atom.render("mean", b"net.sacredchao.Mutagen")
        name = Atom.render("name", b"empty test key")
        bad_freeform = Atom.render("----", b"\x00" * 4 + mean + name)
        self.failUnlessRaises(MP4MetadataError, self.wrap_ilst, bad_freeform)

    def test_pprint_non_text_list(self):
        tags = MP4Tags()
        tags[b"tmpo"] = [120, 121]
        tags[b"trck"] = [(1, 2), (3, 4)]
        tags.pprint()

add(TMP4Tags)

class TMP4(TestCase):
    def setUp(self):
        fd, self.filename = mkstemp(suffix='.m4a')
        os.close(fd)
        shutil.copy(self.original, self.filename)
        self.audio = MP4(self.filename)

    def faad(self):
        if not have_faad: return
        value = os.system("faad %s -o %s > %s 2> %s" % (
                self.filename, devnull, devnull, devnull))
        self.failIf(value and value != NOTFOUND)

    def test_score(self):
        fileobj = open(self.filename, 'rb')
        header = fileobj.read(128)
        self.failUnless(MP4.score(self.filename, fileobj, header))

    def test_channels(self):
        self.failUnlessEqual(self.audio.info.channels, 2)

    def test_sample_rate(self):
        self.failUnlessEqual(self.audio.info.sample_rate, 44100)

    def test_bits_per_sample(self):
        self.failUnlessEqual(self.audio.info.bits_per_sample, 16)

    def test_bitrate(self):
        self.failUnlessEqual(self.audio.info.bitrate, 2914)

    def test_length(self):
        self.failUnlessAlmostEqual(3.7, self.audio.info.length, 1)

    def test_padding(self):
        self.audio[b"\xa9nam"] = "wheeee" * 10
        self.audio.save()
        size1 = os.path.getsize(self.audio.filename)
        MP4(self.audio.filename)
        self.audio[b"\xa9nam"] = "wheeee" * 11
        self.audio.save()
        size2 = os.path.getsize(self.audio.filename)
        self.failUnless(size1, size2)

    def test_padding_2(self):
        self.audio[b"\xa9nam"] = "wheeee" * 10
        self.audio.save()
        # Reorder "free" and "ilst" atoms
        fileobj = open(self.audio.filename, "rb+")
        atoms = Atoms(fileobj)
        meta = atoms["moov", "udta", "meta"]
        meta_length1 = meta.length
        ilst = meta["ilst",]
        free = meta["free",]
        self.failUnlessEqual(ilst.offset + ilst.length, free.offset)
        fileobj.seek(ilst.offset)
        ilst_data = fileobj.read(ilst.length)
        fileobj.seek(free.offset)
        free_data = fileobj.read(free.length)
        fileobj.seek(ilst.offset)
        fileobj.write(free_data + ilst_data)
        fileobj.close()
        fileobj = open(self.audio.filename, "rb+")
        atoms = Atoms(fileobj)
        meta = atoms["moov", "udta", "meta"]
        ilst = meta["ilst",]
        free = meta["free",]
        self.failUnlessEqual(free.offset + free.length, ilst.offset)
        fileobj.close()
        # Save the file
        self.audio[b"\xa9nam"] = "wheeee" * 11
        self.audio.save()
        # Check the order of "free" and "ilst" atoms
        fileobj = open(self.audio.filename, "rb+")
        atoms = Atoms(fileobj)
        fileobj.close()
        meta = atoms["moov", "udta", "meta"]
        ilst = meta["ilst",]
        free = meta["free",]
        self.failUnlessEqual(meta.length, meta_length1)
        self.failUnlessEqual(ilst.offset + ilst.length, free.offset)

    def set_key(self, key, value, result=None, faad=True):
        self.audio[key] = value
        self.audio.save()
        audio = MP4(self.audio.filename)
        self.failUnless(key in audio)
        self.failUnlessEqual(audio[key], result or value)
        if faad:
            self.faad()

    def test_unicode(self):
        self.set_key(b'\xa9nam', [b'\xe3\x82\x8a\xe3\x81\x8b'],
                     result=[u'\u308a\u304b'])

    def test_save_text(self):
        self.set_key(b'\xa9nam', ["Some test name"])

    def test_save_texts(self):
        self.set_key(b'\xa9nam', ["Some test name", "One more name"])

    def test_freeform(self):
        self.set_key(b'----:net.sacredchao.Mutagen:test key', [b"whee"])

    def test_freeform_2(self):
        self.set_key(b'----:net.sacredchao.Mutagen:test key', b"whee", [b"whee"])

    def test_freeforms(self):
        self.set_key(b'----:net.sacredchao.Mutagen:test key', [b"whee", b"uhh"])

    def test_tracknumber(self):
        self.set_key(b'trkn', [(1, 10)])
        self.set_key(b'trkn', [(1, 10), (5, 20)], faad=False)
        self.set_key(b'trkn', [])

    def test_disk(self):
        self.set_key(b'disk', [(18, 0)])
        self.set_key(b'disk', [(1, 10), (5, 20)], faad=False)
        self.set_key(b'disk', [])

    def test_tracknumber_too_small(self):
        self.failUnlessRaises(ValueError, self.set_key, b'trkn', [(-1, 0)])
        self.failUnlessRaises(ValueError, self.set_key, b'trkn', [(2**18, 1)])

    def test_disk_too_small(self):
        self.failUnlessRaises(ValueError, self.set_key, b'disk', [(-1, 0)])
        self.failUnlessRaises(ValueError, self.set_key, b'disk', [(2**18, 1)])

    def test_tracknumber_wrong_size(self):
        self.failUnlessRaises(ValueError, self.set_key, b'trkn', (1,))
        self.failUnlessRaises(ValueError, self.set_key, b'trkn', (1, 2, 3,))
        self.failUnlessRaises(ValueError, self.set_key, b'trkn', [(1,)])
        self.failUnlessRaises(ValueError, self.set_key, b'trkn', [(1, 2, 3,)])

    def test_disk_wrong_size(self):
        self.failUnlessRaises(ValueError, self.set_key, b'disk', [(1,)])
        self.failUnlessRaises(ValueError, self.set_key, b'disk', [(1, 2, 3,)])

    def test_tempo(self):
        self.set_key(b'tmpo', [150])
        self.set_key(b'tmpo', [])

    def test_tempos(self):
        self.set_key(b'tmpo', [160, 200], faad=False)

    def test_tempo_invalid(self):
        for badvalue in [[10000000], [-1], 10, "foo"]:
            self.failUnlessRaises(ValueError, self.set_key, b'tmpo', badvalue)

    def test_compilation(self):
        self.set_key(b'cpil', True)

    def test_compilation_false(self):
        self.set_key(b'cpil', False)

    def test_gapless(self):
        self.set_key(b'pgap', True)

    def test_gapless_false(self):
        self.set_key(b'pgap', False)

    def test_podcast(self):
        self.set_key(b'pcst', True)

    def test_podcast_false(self):
        self.set_key(b'pcst', False)

    def test_cover(self):
        self.set_key(b'covr', [b'woooo'])

    def test_cover_png(self):
        self.set_key(b'covr', [
            MP4Cover(b'woooo', MP4Cover.FORMAT_PNG),
            MP4Cover(b'hoooo', MP4Cover.FORMAT_JPEG),
        ])

    def test_podcast_url(self):
        self.set_key(b'purl', ['http://pdl.warnerbros.com/wbie/justiceleagueheroes/audio/JLH_EA.xml'])

    def test_episode_guid(self):
        self.set_key(b'catg', ['falling-star-episode-1'])

    def test_pprint(self):
        self.failUnless(self.audio.pprint())

    def test_pprint_binary(self):
        self.audio["covr"] = b"\x00\xa9\garbage"
        self.failUnless(self.audio.pprint())

    def test_pprint_pair(self):
        self.audio["cpil"] = (1, 10)
        self.failUnless("cpil=(1, 10)" in self.audio.pprint())

    def test_delete(self):
        self.audio.delete()
        audio = MP4(self.audio.filename)
        self.failIf(audio.tags)
        self.faad()

    def test_module_delete(self):
        delete(self.filename)
        audio = MP4(self.audio.filename)
        self.failIf(audio.tags)
        self.faad()

    def test_reads_unknown_text(self):
        self.set_key(b"foob", ["A test"])

    def __read_offsets(self, filename):
        fileobj = open(filename, 'rb')
        atoms = Atoms(fileobj)
        moov = atoms['moov']
        samples = []
        for atom in moov.findall(b'stco', True):
            fileobj.seek(atom.offset + 12)
            data = fileobj.read(atom.length - 12)
            fmt = ">%dI" % cdata.uint_be(data[:4])
            offsets = struct_unpack(fmt, data[4:])
            for offset in offsets:
                fileobj.seek(offset)
                samples.append(fileobj.read(8))
        for atom in moov.findall(b'co64', True):
            fileobj.seek(atom.offset + 12)
            data = fileobj.read(atom.length - 12)
            fmt = ">%dQ" % cdata.uint_be(data[:4])
            offsets = struct_unpack(fmt, data[4:])
            for offset in offsets:
                fileobj.seek(offset)
                samples.append(fileobj.read(8))
        try:
            for atom in atoms["moof"].findall(b'tfhd', True):
                data = fileobj.read(atom.length - 9)
                flags = cdata.uint_be(b"\x00" + data[:3])
                if flags & 1:
                    offset = cdata.ulonglong_be(data[7:15])
                    fileobj.seek(offset)
                    samples.append(fileobj.read(8))
        except KeyError:
            pass
        fileobj.close()
        return samples

    def test_update_offsets(self):
        aa = self.__read_offsets(self.original)
        self.audio[b"\xa9nam"] = "wheeeeeeee"
        self.audio.save()
        bb = self.__read_offsets(self.filename)
        for a, b in zip(aa, bb):
            self.failUnlessEqual(a, b)

    def test_mime(self):
        self.failUnless("audio/mp4" in self.audio.mime)

    def tearDown(self):
        os.unlink(self.filename)

class TMP4HasTags(TMP4):
    original = os.path.join("tests", "data", "has-tags.m4a")

    def test_save_simple(self):
        self.audio.save()
        self.faad()

    def test_shrink(self):
        for key in self.audio.keys():
            del self.audio[key]
        self.audio.save()
        self.audio = MP4(self.audio.filename)
        self.failIf(self.audio.tags)

    def test_has_tags(self):
        self.failUnless(self.audio.tags)

    def test_has_covr(self):
        self.failUnless(b'covr' in self.audio.tags)
        covr = self.audio.tags[b'covr']
        self.failUnlessEqual(len(covr), 2)
        self.failUnlessEqual(covr[0].imageformat, MP4Cover.FORMAT_PNG)
        self.failUnlessEqual(covr[1].imageformat, MP4Cover.FORMAT_JPEG)

    def test_not_my_file(self):
        self.failUnlessRaises(
            IOError, MP4, os.path.join("tests", "data", "empty.ogg"))

add(TMP4HasTags)

class TMP4CovrWithName(TMP4):
    # http://bugs.musicbrainz.org/ticket/5894
    original = os.path.join("tests", "data", "covr-with-name.m4a")

    def test_has_covr(self):
        self.failUnless(b'covr' in self.audio.tags)
        covr = self.audio.tags[b'covr']
        self.failUnlessEqual(len(covr), 2)
        self.failUnlessEqual(covr[0].imageformat, MP4Cover.FORMAT_PNG)
        self.failUnlessEqual(covr[1].imageformat, MP4Cover.FORMAT_JPEG)

add(TMP4CovrWithName)

class TMP4HasTags64Bit(TMP4HasTags):
    original = os.path.join("tests", "data", "truncated-64bit.mp4")

    def test_has_covr(self):
        pass

    def test_bitrate(self):
        self.failUnlessEqual(self.audio.info.bitrate, 128000)

    def test_length(self):
        self.failUnlessAlmostEqual(0.325, self.audio.info.length, 3)

    def faad(self):
        # This is only half a file, so FAAD segfaults. Can't test. :(
        pass

add(TMP4HasTags64Bit)

class TMP4NoTagsM4A(TMP4):
    original = os.path.join("tests", "data", "no-tags.m4a")

    def test_no_tags(self):
        self.failUnless(self.audio.tags is None)

add(TMP4NoTagsM4A)

class TMP4NoTags3G2(TMP4):
    original = os.path.join("tests", "data", "no-tags.3g2")

    def test_no_tags(self):
        self.failUnless(self.audio.tags is None)

    def test_sample_rate(self):
        self.failUnlessEqual(self.audio.info.sample_rate, 22050)

    def test_bitrate(self):
        self.failUnlessEqual(self.audio.info.bitrate, 32000)

    def test_length(self):
        self.failUnlessAlmostEqual(15, self.audio.info.length, 1)

add(TMP4NoTags3G2)

class TMP4UpdateParents64Bit(TestCase):
    original = os.path.join("tests", "data", "64bit.mp4")

    def setUp(self):
        fd, self.filename = mkstemp(suffix='.mp4')
        os.close(fd)
        shutil.copy(self.original, self.filename)

    def test_update_parents(self):
        file = open(self.filename, 'rb')
        atoms = Atoms(file)
        self.assertEqual(77, atoms.atoms[0].length)
        self.assertEqual(61, atoms.atoms[0].children[0].length)
        tags = MP4Tags(atoms, file)
        tags['pgap'] = True
        tags.save(self.filename)
        file = open(self.filename, 'rb')
        atoms = Atoms(file)
        # original size + 'pgap' size + padding
        self.assertEqual(77 + 25 + 974, atoms.atoms[0].length)
        self.assertEqual(61 + 25 + 974, atoms.atoms[0].children[0].length)

    def tearDown(self):
        os.unlink(self.filename)

add(TMP4UpdateParents64Bit)

NOTFOUND = os.system("tools/notarealprogram 2> %s" % devnull)

have_faad = True
if os.system("faad 2> %s > %s" % (devnull, devnull)) == NOTFOUND:
    have_faad = False
    print("WARNING: Skipping FAAD reference tests.")
