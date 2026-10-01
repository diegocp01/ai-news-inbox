"""Synthetic-only cancellation and atomic CAS regression coverage."""
import copy
import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone

from test_ledger_engine import Repository, ROOT, HASH, T, block, e

sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('cancel_test_gate', ROOT / 'intake_output_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class CancelIntakeTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository().initialize()
        self.repo.execute('receive', request_id='abandoned', expected_items=2)

    def operation(self, **overrides):
        return self.repo.operation('cancel_intake', request_id='abandoned',
            reason_code='user_requested_cancellation', authorization_sha256=HASH,
            expected_request_sha256=e.digest(e.canonical(self.repo.state['requests']['abandoned'])), **overrides)

    def cancel(self):
        op = self.operation()
        plan = e.plan(self.repo.snapshot(), op)
        self.repo.commit(plan)
        return op, plan

    def test_cancellation_keeps_history_count_and_adds_no_record(self):
        before = self.repo.state
        op, plan = self.cancel()
        after = self.repo.state
        self.assertEqual(plan['result']['status'], 'intake_cancelled')
        self.assertFalse(plan['ready_to_send'])
        self.assertFalse(plan['send_authorized'])
        self.assertEqual([p['path'] for p in plan['changes']], [e.LEDGER])
        request = after['requests']['abandoned']
        for key, value in before['requests']['abandoned'].items():
            if key != 'status':
                self.assertEqual(request[key], value)
        self.assertEqual(request['status'], 'cancelled')
        self.assertEqual(request['cancellation'], op)
        for key in ('records', 'next_id', 'batches', 'pending_batch_id', 'checkpoint', 'checkpoint_history'):
            self.assertEqual(after[key], before[key])
        self.assertEqual(e.plan(self.repo.snapshot(), {'kind': 'status'})['result']['unresolved_requests'], [])

    def test_next_intake_can_finalize_after_cancellation(self):
        self.repo.execute('receive', request_id='tomorrow')
        with self.assertRaisesRegex(e.LedgerError, 'earlier'):
            self.repo.execute('finalize', request_id='tomorrow', items=[{'block':block(), 'image_verified':True}])
        self.cancel()
        result = self.repo.execute('finalize', request_id='tomorrow', items=[{'block':block(), 'image_verified':True}])
        self.assertEqual(result['records'][0]['id'], 1)

    def test_replay_has_no_second_change(self):
        op, _ = self.cancel()
        before = self.repo.snapshot()
        retry = e.plan(before, op)
        self.assertEqual(retry['changes'], [])
        self.assertEqual(retry['result']['status'], 'operation_replayed')
        self.repo.commit(retry)
        self.assertEqual(self.repo.snapshot(), before)

    def test_repeated_receive_cannot_reopen_cancelled_request(self):
        self.cancel()
        result = self.repo.execute('receive', request_id='abandoned', expected_items=2)
        self.assertEqual(result['intake_status'], 'cancelled')
        for kind in ('finalize', 'correct', 'reconcile_intake'):
            with self.subTest(kind=kind), self.assertRaisesRegex(e.LedgerError, 'resolved'):
                self.repo.execute(kind, request_id='abandoned')

    def test_missing_authorization_and_extra_private_fields_fail(self):
        good = self.operation()
        for bad in ({k:v for k,v in good.items() if k != 'authorization_sha256'},
                    {**good, 'authorization_sha256':'0'*64},
                    {**good, 'reason_code':'automatic_failure'},
                    {**good, 'private_email_header':'must never persist'}):
            with self.subTest(bad=bad), self.assertRaises(e.LedgerError):
                e.plan(self.repo.snapshot(), bad)

    def test_unknown_and_changed_targets_fail_closed(self):
        op = self.operation()
        for bad in ({**op, 'request_id':'missing'}, {**op, 'expected_request_sha256':'0'*64}):
            with self.subTest(bad=bad), self.assertRaises(e.LedgerError):
                e.plan(self.repo.snapshot(), bad)

    def test_finalized_and_reconciled_requests_cannot_be_cancelled(self):
        self.repo.execute('finalize', request_id='abandoned', items=[{'block':block(), 'image_verified':True}]*2)
        with self.assertRaisesRegex(e.LedgerError, 'Only unresolved'):
            e.plan(self.repo.snapshot(), self.operation())
        self.repo.execute('receive', request_id='reconciled')
        self.repo.execute('reconcile_intake', request_id='reconciled', record_ids=[1], evidence_sha256=HASH)
        op = {**self.operation(), 'request_id':'reconciled',
              'expected_request_sha256':e.digest(e.canonical(self.repo.state['requests']['reconciled']))}
        with self.assertRaisesRegex(e.LedgerError, 'Only unresolved'):
            e.plan(self.repo.snapshot(), op)

    def test_missing_audit_or_modified_expected_count_is_rejected(self):
        op, _ = self.cancel()
        for mutate in ('audit', 'count', 'reopen', 'operation'):
            snapshot = self.repo.snapshot()
            state = json.loads(snapshot['files'][e.LEDGER])
            if mutate == 'audit':
                state['requests']['abandoned'].pop('cancellation')
            elif mutate == 'count':
                state['requests']['abandoned']['expected_items'] = 1
            elif mutate == 'reopen':
                state['requests']['abandoned']['status'] = 'received'
            else:
                state['operations'].pop(op['operation_id'])
            snapshot['files'][e.LEDGER] = e.encoded(state)
            with self.subTest(mutate=mutate), self.assertRaises(e.LedgerError):
                e.plan(snapshot, {'kind':'status'})

    def test_another_unresolved_intake_remains_blocking(self):
        self.repo.execute('receive', request_id='other')
        self.repo.execute('receive', request_id='third')
        self.cancel()
        self.assertEqual(e.plan(self.repo.snapshot(), {'kind':'status'})['result']['unresolved_requests'], ['other','third'])
        with self.assertRaisesRegex(e.LedgerError, 'earlier'):
            self.repo.execute('finalize', request_id='third', items=[{'block':block(), 'image_verified':True}])

    def test_pending_deferred_batch_bytes_and_publication_unchanged(self):
        self.repo = Repository().initialize()
        self.repo.add()
        self.repo.execute('receive', request_id='abandoned', expected_items=2)
        batch = self.repo.execute('prepare', eligibility_at=T)['batch']['batch_id']
        self.repo.execute('publish', batch_id=batch)
        before = self.repo.snapshot()
        self.cancel()
        self.assertEqual(self.repo.state['batches'], json.loads(before['files'][e.LEDGER])['batches'])
        for path, content in before['files'].items():
            if path != e.LEDGER:
                self.assertEqual(self.repo.files[path], content)

    def test_cas_conflict_replans_and_preserves_concurrent_receive(self):
        op = self.operation()
        stale = e.plan(self.repo.snapshot(), op)
        self.repo.execute('receive', request_id='concurrent')
        with self.assertRaisesRegex(e.LedgerError, 'CAS conflict'):
            self.repo.commit(stale)
        fresh = e.plan(self.repo.snapshot(), op)
        self.repo.commit(fresh)
        self.assertEqual(self.repo.state['requests']['concurrent']['status'], 'received')

    def test_definite_write_failure_leaves_received(self):
        plan = e.plan(self.repo.snapshot(), self.operation())
        before = self.repo.snapshot()
        with self.assertRaises(OSError):
            self.repo.commit(plan, fail=True)
        self.assertEqual(self.repo.snapshot(), before)

    def test_lost_accepted_response_is_reconciled_by_same_operation(self):
        op = self.operation()
        self.repo.commit(e.plan(self.repo.snapshot(), op))
        # Simulate a lost response: inspect actual repository state before retry.
        readback = self.repo.snapshot()
        self.assertEqual(self.repo.state['operations'][op['operation_id']]['sha256'], e.digest(e.canonical(op)))
        retry = e.plan(readback, op)
        self.assertFalse(retry['changes'])

    def test_cancel_never_passes_the_intake_output_gate(self):
        op, _ = self.cancel()
        snapshot = self.repo.snapshot()
        observation = {'repository':'diegocp01/ai-news-inbox', 'branch':'main', 'head':snapshot['head'],
                       'observed_at':T, 'snapshot_sha256':e.digest(e.canonical(snapshot))}
        with self.assertRaisesRegex(gate.e.LedgerError, 'finalize or correct'):
            gate.verify_intake_output(snapshot, op, observation, now=datetime.fromisoformat(T))


if __name__ == '__main__':
    unittest.main()
