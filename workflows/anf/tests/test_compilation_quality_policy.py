"""Compilation reuses finalized content; these fixtures assert no real URL access."""
import copy
import json
import unittest
from test_ledger_engine import Repository, ROOT, HASH, T, block, e
from test_editorial_quality import review


class CompilationQualityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository().initialize()
        self.repo.files[e.POLICY] = (ROOT / 'policy.json').read_text()

    def gate(self, value):
        policy = json.loads(self.repo.files[e.POLICY])
        if value is None:
            policy.pop('compilation_quality_gate', None)
        else:
            policy['compilation_quality_gate'] = value
        self.repo.files[e.POLICY] = e.encoded(policy)

    def audience(self, rid=1, technical=False, basis=None, full=False):
        record = e.lookup(self.repo.state, rid)
        ed = review(e.revision(record)['block'], technical, basis)
        if not full:
            ed.pop('quality')
        return self.repo.execute('review_record', record_id=rid,
                                 expected_reference=e.reference(record), editorial=ed)

    def test_current_policy_allows_audience_only_without_quality_assertion(self):
        self.assertIs(json.loads(self.repo.files[e.POLICY])['compilation_quality_gate'], False)
        self.repo.add('General'); self.audience()
        b = self.repo.execute('prepare')['batch']
        self.assertNotIn('quality', b['editorial'][0])
        self.assertNotIn('ds', json.loads(self.repo.files[b['json_path']])[0])
        self.assertEqual(self.repo.files[b['txt_path']], block('General') + e.TRAILER)
        self.repo.execute('publish', batch_id=b['batch_id'])
        self.repo.begin(b['batch_id']); self.repo.acknowledge(b['batch_id'])
        self.assertEqual(self.repo.state['checkpoint'], 1)

    def test_missing_quality_is_blocked_when_enabled_or_default(self):
        for value in (True, None):
            with self.subTest(value=value):
                self.setUp(); self.repo.add('Missing quality'); self.audience(); self.gate(value)
                result = self.repo.execute('prepare')
                self.assertEqual(result['status'], 'empty')
                self.assertIn('reviews are required', result['deferred_records'][0]['reason'])
                with self.assertRaisesRegex(e.LedgerError, 'reviews are required'):
                    self.audience()

    def test_stale_quality_is_ignored_only_when_disabled(self):
        for value in (False, True, None):
            with self.subTest(value=value):
                self.setUp(); self.repo.add('Old quality'); self.audience(full=True); self.gate(value)
                before = copy.deepcopy(self.repo.state['editorial_reviews'])
                result = self.repo.execute('prepare', at='2026-10-05T12:00:00+00:00')
                self.assertEqual(result['status'], 'prepared' if value is False else 'empty')
                self.assertEqual(self.repo.state['editorial_reviews'], before)

    def test_existing_inaccessible_quality_does_not_hold_compilation(self):
        for value in (False, True, None):
            with self.subTest(value=value):
                self.setUp(); self.repo.add('Blocked page'); self.audience(full=True)
                # Simulate imported honest historical evidence, not a successful access.
                state = self.repo.state
                audit = state['editorial_reviews']['1:1'][-1]
                audit['editorial']['quality']['article']['status'] = 'inaccessible_here'
                audit['sha256'] = e.digest(e.canonical(audit['editorial']))
                self.repo.files[e.LEDGER] = e.encoded(state)
                self.gate(value)
                result = self.repo.execute('prepare')
                self.assertEqual(result['status'], 'prepared' if value is False else 'empty')
                if value is False:
                    self.assertEqual(result['batch']['editorial'][0]['quality']['article']['status'], 'inaccessible_here')

    def test_missing_audience_still_defers_with_quality_disabled(self):
        self.repo.add('Unclassified')
        result = self.repo.execute('prepare')
        self.assertEqual(result['status'], 'empty')
        self.assertIn('audience', result['deferred_records'][0]['reason'])
        ed = review(block('Unclassified')); ed.pop('audience')
        with self.assertRaises(e.LedgerError):
            self.repo.execute('review_record', record_id=1,
                expected_reference=e.reference(self.repo.state['records'][0]), editorial=ed)

    def test_datasciencecorner_requires_technical_audience_without_quality(self):
        self.repo.execute('receive', request_id='ds', origin={'kind':'data_science_corner', 'evidence_sha256':HASH})
        self.repo.execute('finalize', request_id='ds', items=[{'block':block('Paper'), 'image_verified':True}])
        with self.assertRaisesRegex(e.LedgerError, 'DataScienceCorner'):
            self.audience()
        self.audience(technical=True, basis='data_science_corner')
        b = self.repo.execute('prepare')['batch']
        self.assertIs(json.loads(self.repo.files[b['json_path']])[0]['ds'], True)
        self.assertIn('\nds: true', self.repo.files[b['txt_path']])

    def test_explicit_rejection_blocks_without_quality(self):
        self.repo.add('Rejected'); self.audience()
        self.repo.execute('reject_url', url='https://example.com/image.png', field='image', scope='url',
                          environment='editorial', reason='irrelevant_image', evidence_sha256=HASH)
        result = self.repo.execute('prepare')
        self.assertEqual(result['status'], 'empty')
        self.assertIn('evidenced rejection', result['deferred_records'][0]['reason'])

    def test_late_rejection_blocks_frozen_audience_only_batch(self):
        for published in (False, True):
            with self.subTest(published=published):
                self.setUp(); self.repo.add('Frozen'); self.audience()
                bid = self.repo.published() if published else self.repo.prepared()
                b = self.repo.state['batches'][bid]
                frozen = {p:self.repo.files[p] for p in (b['txt_path'], b['json_path'])}
                self.repo.execute('reject_url', url='https://example.com/news', field='article', scope='url',
                                  environment='editorial', reason='not_same_event', evidence_sha256=HASH)
                with self.assertRaisesRegex(e.LedgerError, 'active evidenced rejection'):
                    self.repo.begin(bid) if published else self.repo.execute('publish', batch_id=bid)
                for p, value in frozen.items():
                    self.assertEqual(self.repo.files[p], value)

    def test_policy_change_preserves_old_frozen_bytes_and_delivery(self):
        self.gate(True); self.repo.add('Already frozen'); self.audience(full=True)
        bid = self.repo.prepared(); before = copy.deepcopy(self.repo.state['batches'][bid])
        paths = (before['txt_path'], before['json_path'])
        frozen = {p:self.repo.files[p] for p in paths}
        self.gate(False)
        self.assertEqual(self.repo.execute('prepare')['batch'], before)
        self.repo.execute('publish', batch_id=bid); self.repo.begin(bid); self.repo.acknowledge(bid)
        for p, value in frozen.items():
            self.assertEqual(self.repo.files[p], value)

    def test_full_quality_assertions_remain_strict_and_intake_unchanged(self):
        self.repo.add('Bad assertions')
        ed = review(block('Bad assertions')); ed['quality']['image']['pixels_inspected'] = False
        with self.assertRaisesRegex(e.LedgerError, 'pixels'):
            self.repo.execute('review_record', record_id=1,
                expected_reference=e.reference(self.repo.state['records'][0]), editorial=ed)
        self.repo.execute('receive', request_id='unverified')
        with self.assertRaisesRegex(e.LedgerError, 'verified'):
            self.repo.execute('finalize', request_id='unverified', items=[{'block':block('New')}])

    def test_domain_restrictions_apply_without_quality_and_to_known_redirects(self):
        self.repo.add('Safety'); self.audience(full=True)
        for url in ('https://blocked.ai/news', 'https://openai.com/news'):
            with self.assertRaisesRegex(e.LedgerError, 'policy'):
                e.validate_editorial({'audience':review(block())['audience']},
                    {'block':block('Bad', url=url)}, {}, json.loads(self.repo.files[e.POLICY]), require_quality=False)
        ed = review(block('Safety')); ed['quality']['article']['redirect_chain'].append('https://blocked.ai/final')
        with self.assertRaisesRegex(e.LedgerError, 'policy'):
            e.validate_editorial(ed, {'block':block('Safety')}, {}, json.loads(self.repo.files[e.POLICY]), require_quality=False)

    def test_flag_must_be_boolean(self):
        for value in ('false', 0, 1):
            self.gate(value)
            with self.assertRaisesRegex(e.LedgerError, 'compilation quality policy'):
                self.repo.execute('status')


if __name__ == '__main__':
    unittest.main()
