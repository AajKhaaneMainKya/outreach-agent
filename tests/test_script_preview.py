import unittest
from gtm import playbook

class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.f={'icp':'spa','business':'Example Spa','sender':'Rahul','staff':'Isabelle','hook':'warm and welcoming'}
        self.r={'reviews':[{'stars':5,'text':'Isabelle was warm and welcoming.'}]}
    def test_unverified_proposal_never_releases(self):
        before=dict(self.f)
        p=playbook.research_preview(self.f,self.r,{'qa_pass':True})
        self.assertTrue(p['available']);self.assertFalse(p['release_allowed'])
        self.assertEqual(self.f,before)
        self.assertEqual(p['draft']['money_line'],'You pay one flat fee. Nobody is paid per patient, in either direction.')
    def test_exclusion_and_qa_block_preview(self):
        for a in ({'qa_pass':False},{'qa_pass':True,'qualification_notice':'excluded'}):
            self.assertFalse(playbook.research_preview(self.f,self.r,a)['available'])
    def test_no_fabricated_or_cross_review_hook(self):
        self.f['hook']='invented praise'
        self.assertFalse(playbook.research_preview(self.f,self.r,{'qa_pass':True})['available'])
        self.f['hook']='warm and welcoming';self.r['reviews']=[{'stars':5,'text':'Isabelle was nice.'},{'stars':5,'text':'Someone was warm and welcoming.'}]
        self.assertFalse(playbook.research_preview(self.f,self.r,{'qa_pass':True})['available'])
    def test_unsafe_results_hook_blocked(self):
        self.f['hook']='lost pounds';self.r['reviews'][0]['text']='Isabelle helped me lost pounds'
        self.assertFalse(playbook.research_preview(self.f,self.r,{'qa_pass':True})['available'])
