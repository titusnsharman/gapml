import unittest

from allele import Allele
from barcode_metadata import BarcodeMetadata
from random import seed, randint, choice

class AlleleTestCase(unittest.TestCase):
    def setUp(self):
        self.NUM_TARGETS = 4
        self.ORIG_BARCODE = [
                "A",
                "TATCTT",
                "TAT",
                "TACCAT",
                "ACG",
                "GGCGAG",
                "ATG",
                "GTTGAG",
                "C"]
        self.TARGET_LEN = len(self.ORIG_BARCODE[1])
        self.SEP_LEN = len(self.ORIG_BARCODE[2])
        self.CUT_SITE_NUM = 3
        self.CUT_SITES = [self.CUT_SITE_NUM] * self.NUM_TARGETS
        self.barcode_meta = BarcodeMetadata(
                self.ORIG_BARCODE,
                self.CUT_SITES,
                [3,3])
        self.allele = Allele(
            self.ORIG_BARCODE, self.barcode_meta)

    def test_active_targets(self):
        active_targets = self.allele.get_active_targets()
        self.assertEqual(
            set(active_targets),
            set(range(self.NUM_TARGETS)))

        self.allele.cut(0)
        active_targets = self.allele.get_active_targets()
        self.assertEqual(
            set(active_targets),
            set(range(1,self.NUM_TARGETS)))

        self.allele.indel(0, 0, 0, 0, "")
        active_targets = self.allele.get_active_targets()
        self.assertEqual(
            set(active_targets),
            set(range(self.NUM_TARGETS)))

        self.allele.cut(0)
        self.allele.indel(0, 0, 0, 0, "atcg")
        active_targets = self.allele.get_active_targets()
        self.assertEqual(
            set(active_targets),
            set(range(1, self.NUM_TARGETS)))

    def test_indel(self):
        self.allele.cut(0)
        self.assertEqual(self.allele.needs_repair, set([0]))
        self.allele.indel(0, 0, 1, 2, "atcg")
        allele_str = str(self.allele)
        true_prefix = "%s%s-atcg--%s" % (
            self.ORIG_BARCODE[0],
            self.ORIG_BARCODE[1][:self.TARGET_LEN - self.CUT_SITE_NUM - 1],
            self.ORIG_BARCODE[1][-self.CUT_SITE_NUM + 2:])
        self.assertTrue(allele_str.startswith(true_prefix))
        self.assertTrue(len(self.allele.needs_repair) == 0)

        self.allele.cut(1)
        self.allele.cut(3)
        self.assertEqual(self.allele.needs_repair, set([1,3]))
        # cut off 4 to the left, which cuts thru to a separator sequence
        # cut off 6 to the right, though the sequence actually only has 4 more to the right
        self.allele.indel(1, 3, 4, 6, "atcg")
        allele_str = str(self.allele)
        true_suffix = "%s%satcg%s" % (
            self.ORIG_BARCODE[2][:-1],
            "-" * 4,
            "-" * (4 + (self.TARGET_LEN + self.SEP_LEN) * 2))
        self.assertTrue(allele_str.endswith(true_suffix))
        self.assertTrue(len(set(self.allele.needs_repair)) == 0)

    def test_events(self):
        evts = self.allele.get_events()
        self.assertEqual(len(evts), 0)

        self.allele.cut(0)
        self.allele.indel(0, 0, 1, 2, "atcg")
        evts = self.allele.get_events()
        self.assertEqual(evts, [(3, 6, "atcg")])

    def test_process_events(self):
        evts = [(0, 6, "atcg"), (10, 27, ""), (35, 35, "atgc")]
        self.allele.process_events(evts)
        self.assertTrue(self.allele.get_events(), evts)

    def test_process_get_events(self):
        """
        Given an event tuple, if we process the event into the allele, then ask
        for it back, we should get the same event. Let's test this with 1000
        random events plus a few special cases.
        """
        allele_str_len = len(str(self.allele))
        evts_list = []
        for _ in range(1000):
            evt_start = randint(0, allele_str_len - 1)
            evt_end = randint(evt_start, allele_str_len)
            insertion_len = randint(0 if evt_end > evt_start else 1, 10)
            insertion = ''.join([choice('acgt') for _ in range(insertion_len)])
            evts_list.append([(evt_start, evt_end, insertion)])
        # special case 1: insertion off the 3' end
        evts_list.append([(allele_str_len, allele_str_len, 'acgt')])
        # special case 2: make sure multiple events don't interact in unexpected ways
        evts_list.append([(1, 4, ''), (5, 5, 'tac')])
        evts_list.append([(2, 2, 'acg'), (3, 5, '')])
        for evts in evts_list:
            self.allele = Allele(
                self.ORIG_BARCODE,
                self.barcode_meta)
            self.allele.process_events(evts)
            evts_get = self.allele.get_events()
            self.assertTrue(evts_get == evts,
                            '\n  processed event: {}\n        got event: {}\n    processed seq: {}'
                            .format(evts, evts_get, self.allele.allele))