"""Grayscale mapping used by the bookmark generator."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
DIR=ROOT/'tools'
spec=importlib.util.spec_from_file_location('bookmark',DIR/'bookmark_relief.py')
bookmark=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bookmark)


class BookmarkTests(unittest.TestCase):
    def test_gray_mapping_and_bad_calibration(self):
        tones=np.linspace(0,255,11)
        self.assertEqual(bookmark.gray_to_layers(tones,tones).tolist(),list(range(11)))
        values=bookmark.gray_to_layers(np.arange(256),tones)
        self.assertTrue(np.all(np.diff(values)>=0))
        for invalid in ([0]*11, [0,255], [float('nan')]*11):
            with self.assertRaises(ValueError): bookmark.gray_to_layers([0,128,255],invalid)
