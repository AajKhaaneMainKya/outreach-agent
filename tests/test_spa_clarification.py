import unittest
import test_playbook
from gtm import playbook
class SpaClarificationTests(unittest.TestCase):
 def test_discovery_does_not_add_a_facials_requirement(self):
  p=playbook.policy();self.assertIn('massage spa',p['spa']['search']);self.assertFalse(p['spa_classification_clarification']['facials_are_required'])
 def test_qualified_independent_massage_day_spa_is_not_excluded(self):
  f=test_playbook.facts();f.update(icp='spa',menu='Swedish massage, deep tissue massage, sauna',independent=True,owner_run=True,locations=1,staff_count=3,reviews=50,years_open=2,chain=False,franchise=False)
  self.assertEqual('qualified',playbook.qualification(f)[0])
 def test_search_term_never_overrides_threshold_or_skip(self):
  f=test_playbook.facts();f.update(icp='spa',menu='Massage spa with filler',independent=True,owner_run=True,locations=1,staff_count=3,reviews=50,years_open=2,chain=False,franchise=False)
  self.assertEqual('skip',playbook.qualification(f)[0]);f['menu']='Massage';f['staff_count']=2;self.assertEqual('skip',playbook.qualification(f)[0])
