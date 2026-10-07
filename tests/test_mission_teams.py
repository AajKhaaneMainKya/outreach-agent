import unittest
from gtm.mission import research_batch
class BatchTests(unittest.TestCase):
 def test_default(self):self.assertEqual({'limit':6,'team_count':3},research_batch('Find spas in Florida'))
 def test_single(self):self.assertEqual({'limit':1,'team_count':1},research_batch('Find 1 spa in Florida'))
 def test_explicit(self):self.assertEqual({'limit':10,'team_count':3},research_batch('Research 10 businesses in Florida'))
 def test_bound(self):self.assertRaises(ValueError,research_batch,'Find 100 spas in Florida')
