import unittest
from gtm.mission import geography,intent
from gtm.playbook_campaigns import settings
class MissionJourneyTests(unittest.TestCase):
 def test_city_in_question(self):
  self.assertEqual('Austin, Texas',geography('Find a spa in Austin, Texas and prepare a draft')['city'])
 def test_no_city_is_us_wide(self):
  self.assertEqual('United States',geography('Find a qualifying spa and prepare outreach')['city'])
 def test_explicit_national_overrides_old_city_reference(self):
  self.assertEqual('United States',geography('Search US-wide, not just Austin')['city'])
 def test_bare_city(self):self.assertEqual('Seattle',geography('Find Seattle spas')['city'])
 def test_arbitrary_city(self):self.assertEqual('Bozeman, Montana',geography('Find dietitians near Bozeman, Montana with cash-pay services')['city'])
 def test_near_me_does_not_assume_user_location(self):self.assertEqual('United States',geography('Find spas near me')['city'])
 def test_policy_clause_not_location(self):self.assertEqual('United States',geography('Find a spa in accordance with VJ rules')['city'])
 def test_hook_request_is_not_new_discovery(self):self.assertEqual('continue',intent('Find an exact hook for this saved review'))
 def test_provider_request_is_discovery(self):self.assertEqual('discover',intent('Find a spa in Boston'))
 def test_prompt_overrides_stale_form_city_and_timezone(self):
  s=settings({'icp':'spa','source':'web','city':'Austin','timezone':'America/Chicago','sender':'Rahul','limit':1,'prompt_scope':True,'agent_goal':'Find a spa in Seattle and prepare a draft'})
  self.assertEqual('Seattle',s['city']);self.assertEqual('',s['timezone'])
 def test_default_never_reuses_previous_city(self):
  s=settings({'icp':'spa','source':'web','city':'Austin','timezone':'America/Chicago','sender':'Rahul','limit':1,'prompt_scope':True,'agent_goal':'Find a qualifying spa'})
  self.assertEqual('United States',s['city']);self.assertEqual('',s['timezone'])

 def test_bare_arbitrary_city_after_category(self):self.assertEqual('Boise',geography('Find spas Boise and prepare outreach')['city'])
 def test_bare_arbitrary_city_before_category(self):self.assertEqual('Bangor',geography('Find Bangor spas')['city'])

 def test_country_scope_is_not_a_verified_prospect_city(self):
  from gtm.playbook_campaigns import prefill
  research={'place_details':{'displayName':{'text':'Spa'}},'website':'https://example.com','evidence':[],'reviews':[]}
  s={'city':'United States','icp':'spa','sender':'Rahul','timezone':'','geography_resolution':{'scope':'national'}}
  self.assertEqual('',prefill(research,{'facts':{}},s)['city'])
