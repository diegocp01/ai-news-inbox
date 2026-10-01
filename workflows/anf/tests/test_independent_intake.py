import copy
import unittest
from datetime import datetime
from test_ledger_engine import Repository, block, e, HASH, T
from test_intake_output_gate import gate

LATE = '2026-09-30T16:00:00+00:00'

class IndependentIntakeTests(unittest.TestCase):
    def setUp(self):
        self.r = Repository().initialize()
        self.r.execute('receive', request_id='unfinished', expected_items=2)
        self.pending = copy.deepcopy(self.r.state['requests']['unfinished'])

    def test_earlier_intake_finishes_after_publication_without_changing_batch(self):
        r = self.r
        r.add('Ready later', request='manual')
        self.assertEqual(r.state['requests']['unfinished'], self.pending)
        b = r.execute('prepare', eligibility_at=T)['batch']
        self.assertEqual([x['id'] for x in b['records']], [1])
        self.assertEqual(b['deferred_request_ids'], ['unfinished'])
        pub = r.execute('publish', batch_id=b['batch_id'])['publication']
        frozen = {p: r.files[p] for p in (b['txt_path'], b['json_path'], pub['path'])}
        r.execute('finalize', request_id='unfinished', at=LATE, items=[
            {'block': block('Late one'), 'image_verified': True},
            {'block': block('Late two'), 'image_verified': True}])
        self.assertEqual([x['id'] for x in r.state['requests']['unfinished']['records']], [2, 3])
        self.assertEqual(r.state['checkpoint'], 0)
        self.assertEqual(r.execute('prepare', at=LATE, eligibility_at=LATE)['batch']['records'], b['records'])
        r.execute('begin_delivery', at=LATE, batch_id=b['batch_id'], attempt_id='send', target_sha256=HASH)
        r.execute('acknowledge', at=LATE, batch_id=b['batch_id'], attempt_id='send', receipt=r.receipt(b['batch_id'], accepted_at=LATE))
        self.assertEqual(r.state['checkpoint'], 1)
        self.assertEqual(frozen, {p: r.files[p] for p in frozen})
        following = r.execute('prepare', at=LATE, eligibility_at=LATE)['batch']
        self.assertEqual([x['id'] for x in following['records']], [2, 3])

    def test_output_gate_releases_independent_committed_result(self):
        r = self.r
        r.execute('receive', request_id='manual')
        op = r.operation('finalize', request_id='manual', items=[{'block': block('Ready'), 'image_verified': True}])
        r.commit(e.plan(r.snapshot(), op))
        snapshot = r.snapshot()
        observation = {'repository': gate.REPOSITORY, 'branch': 'main', 'head': snapshot['head'], 'observed_at': T,
                       'snapshot_sha256': e.digest(e.canonical(snapshot))}
        out = gate.verify_intake_output(snapshot, op, observation, now=datetime.fromisoformat(T))
        self.assertTrue(out['ready_to_send'])
        self.assertEqual(out['items'][0]['block'], block('Ready'))
        self.assertEqual(r.state['requests']['unfinished'], self.pending)

    def test_independent_duplicate_and_reconciliation_do_not_allocate_ids(self):
        r = self.r
        r.add('Ready', request='manual')
        r.add('Ready', request='duplicate')
        self.assertEqual(r.state['next_id'], 2)
        r.execute('receive', request_id='reconcile')
        r.execute('reconcile_intake', request_id='reconcile', record_ids=[1], evidence_sha256=HASH)
        self.assertEqual(r.state['requests']['unfinished'], self.pending)
        self.assertEqual(r.state['next_id'], 2)

    def test_unrelated_intake_does_not_block_correction_but_same_target_does(self):
        r = self.r
        r.add('Ready', request='manual')
        r.execute('receive', request_id='c1', corrects_record_id=1)
        r.execute('receive', request_id='c2', corrects_record_id=1)
        with self.assertRaisesRegex(e.LedgerError, 'earlier received corrections'):
            r.execute('correct', request_id='c2', record_id=1, block=block('Later'), image_verified=True)
        r.execute('correct', request_id='c1', record_id=1, block=block('Earlier'), image_verified=True)
        r.execute('correct', request_id='c2', record_id=1, block=block('Later'), image_verified=True)
        self.assertEqual(r.state['requests']['unfinished'], self.pending)
        self.assertEqual(len(r.state['records'][0]['revisions']), 3)

    def test_failed_multi_item_completion_leaves_both_requests_unchanged(self):
        r = self.r
        r.execute('receive', request_id='manual', expected_items=2)
        before = r.snapshot()
        with self.assertRaises(e.LedgerError):
            r.execute('finalize', request_id='manual', items=[{'block': block('Valid'), 'image_verified': True}, {'block': 'invalid', 'image_verified': True}])
        self.assertEqual(r.snapshot(), before)

if __name__ == '__main__':
    unittest.main()
