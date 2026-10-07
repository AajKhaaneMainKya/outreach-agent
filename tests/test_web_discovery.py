import unittest
from unittest.mock import patch
from gtm import web_discovery
from scripts.search_mcp import Search

class WebDiscoveryTests(unittest.TestCase):
 def test_no_search_facts_invented(self):
  rows=[{'title':'Ceremony Spa','href':'https://ceremonyspa.com/','body':'A spa in Austin'}]
  with patch.object(web_discovery,'search',return_value=rows),patch('gtm.providers.public_target'):
   p=web_discovery.discover('day spa','Austin')[0]
  self.assertTrue(p['place_id'].startswith('web-'));self.assertEqual('',p['address'])
  self.assertNotIn('phone',p);self.assertNotIn('reviews',p);self.assertEqual('Austin',p['search_city'])
 def test_directory_and_private_results_filtered(self):
  rows=[{'title':'Yelp','href':'https://www.yelp.com/x'},{'title':'Local','href':'http://127.0.0.1/'}]
  with patch.object(web_discovery,'search',return_value=rows),patch('gtm.providers.public_target',side_effect=ValueError('private')):
   self.assertEqual([],web_discovery.discover('day spa','Austin'))
 def test_unique_domain(self):
  rows=[{'title':'Ceremony','href':'https://ceremonyspa.com/'},{'title':'Team','href':'https://ceremonyspa.com/team'}]
  with patch.object(web_discovery,'search',return_value=rows),patch('gtm.providers.public_target'):
   self.assertEqual(1,len(web_discovery.discover('day spa','Austin')))
 def test_term_and_scope_enforced(self):
  s=Search({'icp':'spa','city':'Austin'})
  with patch.object(web_discovery,'discover') as discover:
   self.assertRaises(ValueError,s.call,'search_businesses',{'search_term':'invented'})
   self.assertRaises(ValueError,s.call,'place_details',{'place_id':'invented'});discover.assert_not_called()
 def test_budget(self):
  s=Search({'icp':'spa','city':'Austin'});s.calls=6
  self.assertTrue(s.call('search_businesses',{})['unavailable'])
 def test_provider_failure_surfaces_without_results(self):
  with patch.object(web_discovery,'search',side_effect=ValueError('unavailable')):
   self.assertRaises(ValueError,web_discovery.discover,'day spa','Austin')

 def test_editorial_roundups_are_not_businesses(self):
  rows=[{'title':'10 Incredible Luxury Spa Resorts In Florida','href':'https://floridatrippers.com/best-spa-resorts-in-florida/'},
        {'title':'Luxurious Florida Spas and Wellness Centers','href':'https://www.visitflorida.com/travel-ideas/articles/florida-spas-wellness-centers/'},
        {'title':'7 Incredible Luxury Spa Resorts In Florida','href':'https://independent-travel.test/florida-spas'},
        {'title':'Regional Spa Guide','href':'https://travel.test/articles/spa-guide/'}]
  with patch.object(web_discovery,'search',return_value=rows),patch('gtm.providers.public_target'):
   self.assertEqual([],web_discovery.discover('day spa','Florida'))
 def test_actual_business_resort_and_single_location_page_retained(self):
  rows=[{'title':'DayDreams Day Spa | Top Rated Spa in Lakeland, FL','href':'https://www.daydreamsdayspa.com/lakeland/'},
        {'title':'The Palms Resort & Spa','href':'https://actual-resort.test/spa/'},
        {'title':'Florida Wellness Center','href':'https://actual-practice.test/'}]
  with patch.object(web_discovery,'search',return_value=rows),patch('gtm.providers.public_target'):
   self.assertEqual(3,len(web_discovery.discover('day spa','Florida')))
