import unittest
from unittest.mock import patch
from gtm import web_discovery as wd,playbook
class DirectoryResolutionTests(unittest.TestCase):
 def test_regional_and_individual_directory_urls_are_not_businesses(self):
  self.assertFalse(wd.business_lead('20 Best Dieticians and Nutritionists In Florida - Healthgrades','https://www.healthgrades.com/diet-nutrition-directory/fl-florida'))
  self.assertFalse(wd.business_lead('Nutritionists and Dietitians in Florida - HealthProfs.com','https://www.healthprofs.com/us/nutritionists-dietitians/florida'))
  self.assertFalse(wd.business_lead('Jane Doe RDN','https://www.healthprofs.com/us/nutritionists-dietitians/jane-doe-fl/12345'))
 def test_listing_resolves_profile_to_external_practice_with_provenance(self):
  directory='https://www.healthprofs.com/us/nutritionists-dietitians/florida';profile='https://www.healthprofs.com/us/nutritionists-dietitians/jane-doe-fl/12345';website='https://nutritionpractice.test/'
  pages=[{'url':directory,'links':[profile],'text':'Listings'}, {'url':profile,'links':[website],'text':'Jane Doe nutrition practice'}]
  with patch.object(wd,'search',return_value=[{'title':'Florida dietitians','href':directory}]),patch('gtm.providers.fetch_website',side_effect=pages),patch('gtm.providers.public_target'):
   leads=wd.discover('dietitian','Florida',3)
  self.assertEqual(website,leads[0]['website']);self.assertEqual(profile,leads[0]['discovery_provenance']['profile_url']);self.assertNotIn('reviews',leads[0]);self.assertNotIn('rdn_count',leads[0])
 def test_blocked_directory_falls_back_to_direct_search(self):
  rows=[[{'title':'Directory','href':'https://www.healthgrades.com/diet-nutrition-directory/fl-florida'}],[{'title':'Nutrition Practice','href':'https://nutritionpractice.test/'}]]
  with patch.object(wd,'search',side_effect=rows) as search,patch('gtm.providers.fetch_website',side_effect=ValueError('unavailable')),patch('gtm.providers.public_target'):
   leads=wd.discover('dietitian','Florida')
  self.assertEqual('Nutrition Practice',leads[0]['name']);self.assertIn('-site:healthgrades.com',search.call_args.args[0])
 def test_shared_directory_read_budget(self):
  with patch('gtm.providers.fetch_website') as fetch:
   self.assertEqual([],wd.resolve_directory({'href':'https://healthprofs.com/us/nutritionists-dietitians/florida'},'Florida',[0]));fetch.assert_not_called()
 def test_directory_does_not_get_script_even_after_qa(self):
  preview=playbook.research_preview({'website':'https://healthgrades.com/diet-nutrition-directory/fl-florida'},{},{'qa_pass':True})
  self.assertFalse(preview['available']);self.assertNotIn('draft',preview)
