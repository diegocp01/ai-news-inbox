import copy
import unittest
from test_ledger_engine import Repository, block, e, HASH, T

LATE = '2026-09-30T16:00:00+00:00'


class CompilationCutoffTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository().initialize()

    def test_unfinished_request_preserved_and_later_items_reach_next_batch(self):
        r = self.repo
        r.add('Ready')
        r.execute('receive', request_id='unfinished', expected_items=2)
        request = copy.deepcopy(r.state['requests']['unfinished'])
        b = r.execute('prepare', eligibility_at=T)['batch']
        self.assertEqual(b['deferred_request_ids'], ['unfinished'])
        self.assertEqual(r.state['requests']['unfinished'], request)
        self.assertEqual(r.state['checkpoint'], 0)
        r.execute('publish', batch_id=b['batch_id'])
        r.begin(b['batch_id'])
        r.acknowledge(b['batch_id'])
        self.assertEqual(r.state['checkpoint'], 1)
        self.assertEqual(r.state['requests']['unfinished'], request)
        r.execute('finalize', request_id='unfinished', at=LATE, items=[
            {'block': block('Late one'), 'image_verified': True},
            {'block': block('Late two'), 'image_verified': True}])
        following = r.execute('prepare', at=LATE, eligibility_at=LATE)['batch']
        self.assertEqual([ref['id'] for ref in following['records']], [2, 3])
        self.assertEqual(following['checkpoint_before'], 1)

    def test_late_finalization_before_retry_cannot_change_frozen_membership(self):
        r = self.repo
        r.add('Ready')
        r.execute('receive', request_id='unfinished')
        b = r.execute('prepare', eligibility_at=T)['batch']
        txt = r.files[b['txt_path']]
        r.execute('finalize', request_id='unfinished', at=LATE,
                  items=[{'block': block('Late'), 'image_verified': True}])
        retry = r.execute('prepare', at=LATE, eligibility_at=LATE)['batch']
        self.assertEqual(retry, b)
        self.assertEqual(r.files[b['txt_path']], txt)
        r.execute('publish', batch_id=b['batch_id'], at=LATE)
        r.execute('begin_delivery', batch_id=b['batch_id'], attempt_id='later_send', target_sha256=HASH, at=LATE)
        r.execute('acknowledge', batch_id=b['batch_id'], attempt_id='later_send',
                  receipt=r.receipt(b['batch_id'], accepted_at=LATE), at=LATE)
        self.assertEqual(r.state['checkpoint'], 1)
        self.assertEqual(r.execute('prepare', at=LATE, eligibility_at=LATE)['batch']['first_id'], 2)

    def test_retry_after_cutoff_excludes_already_finalized_late_arrival(self):
        r = self.repo
        r.add('Ready')
        r.execute('receive', request_id='late', at=LATE)
        r.execute('finalize', request_id='late', at=LATE,
                  items=[{'block': block('Late'), 'image_verified': True}])
        b = r.execute('prepare', at=LATE, eligibility_at=T)['batch']
        self.assertEqual([ref['id'] for ref in b['records']], [1])

    def test_late_correction_never_skips_earlier_id(self):
        r = self.repo
        r.add('One')
        r.add('Two')
        r.execute('receive', request_id='correction', corrects_record_id=1, at=LATE)
        r.execute('correct', request_id='correction', record_id=1,
                  block=block('One corrected'), image_verified=True, at=LATE)
        self.assertEqual(r.execute('prepare', at=LATE, eligibility_at=T)['status'], 'empty')
        self.assertEqual(r.state['checkpoint'], 0)
        self.assertEqual(r.execute('prepare', at=LATE, eligibility_at=LATE)['batch']['count'], 2)

    def test_pending_selected_correction_still_blocks(self):
        r = self.repo
        r.add('Ready')
        r.execute('receive', request_id='correction', corrects_record_id=1)
        with self.assertRaisesRegex(e.LedgerError, 'Unresolved intakes'):
            r.execute('prepare', eligibility_at=T)

    def test_later_correction_to_frozen_member_still_blocks(self):
        r = self.repo
        r.add('Ready')
        r.execute('receive', request_id='unfinished')
        b = r.execute('prepare', eligibility_at=T)['batch']
        r.execute('receive', request_id='correction', corrects_record_id=1)
        with self.assertRaisesRegex(e.LedgerError, 'Unresolved intakes'):
            r.execute('publish', batch_id=b['batch_id'])
        with self.assertRaisesRegex(e.LedgerError, 'Unresolved intakes'):
            r.execute('prepare', eligibility_at=T)

    def test_correction_replacement_keeps_cutoff_and_deferrals(self):
        r = self.repo
        r.add('Ready')
        r.execute('receive', request_id='correction', corrects_record_id=1)
        r.execute('correct', request_id='correction', record_id=1, block=block('First correction'), image_verified=True)
        r.execute('receive', request_id='unfinished')
        b = r.execute('prepare', eligibility_at=T)['batch']
        r.execute('finalize', request_id='unfinished', at=LATE,
                  items=[{'block': block('Late'), 'image_verified': True}])
        r.execute('receive', request_id='correction2', corrects_record_id=1, at=LATE)
        r.execute('correct', request_id='correction2', record_id=1,
                  block=block('Second correction'), image_verified=True, at=LATE)
        replacement = r.execute('prepare', at=LATE, eligibility_at=LATE)['batch']
        self.assertEqual(replacement['eligibility_at'], T)
        self.assertEqual(replacement['deferred_request_ids'], b['deferred_request_ids'])
        self.assertEqual(replacement['intake_cutoff'], b['intake_cutoff'])
        self.assertEqual([ref['id'] for ref in replacement['records']], [1])
        r.execute('publish', batch_id=replacement['batch_id'], at=LATE)

    def test_future_cutoff_rejected_and_empty_does_not_resolve_intake(self):
        r = self.repo
        r.execute('receive', request_id='unfinished')
        with self.assertRaisesRegex(e.LedgerError, 'future'):
            r.execute('prepare', eligibility_at=LATE)
        self.assertEqual(r.execute('prepare', eligibility_at=T)['status'], 'empty')
        self.assertEqual(r.state['requests']['unfinished']['status'], 'received')
        self.assertEqual(r.state['checkpoint'], 0)

    def test_corrupt_deferred_selected_correction_rejected(self):
        r = self.repo
        r.add('Ready')
        b = r.execute('prepare', eligibility_at=T)['batch']
        r.execute('receive', request_id='correction', corrects_record_id=1)
        state = r.state
        state['batches'][b['batch_id']]['deferred_request_ids'] = ['correction']
        state['batches'][b['batch_id']]['intake_cutoff'] = state['requests']['correction']['received_sequence']
        r.files[e.LEDGER] = e.encoded(state)
        with self.assertRaisesRegex(e.LedgerError, 'selected-record correction'):
            r.execute('status')


if __name__ == '__main__':
    unittest.main()
