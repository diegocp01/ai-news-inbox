import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from test_ledger_engine import Repository, e, block, T

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules["ledger_engine"] = e
import intake_output_gate as gate


class IntakeOutputGateTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository().initialize()
        self.repo.execute('receive', request_id='intake')
        self.op = self.repo.operation('finalize', request_id='intake', items=[
            {'block': block('Gate example'), 'source': 'Example', 'image_verified': True}])
        self.plan = e.plan(self.repo.snapshot(), self.op)
        self.now = datetime.fromisoformat(T)

    def observe(self, snapshot=None):
        snapshot = snapshot or self.repo.snapshot()
        return {'repository': gate.REPOSITORY, 'branch': 'main', 'head': snapshot['head'],
                'observed_at': T, 'snapshot_sha256': e.digest(e.canonical(snapshot))}

    def verify(self, snapshot=None, operation=None, observation=None, now=None):
        snapshot = snapshot or self.repo.snapshot()
        return gate.verify_intake_output(snapshot, operation or self.op,
            observation if observation is not None else self.observe(snapshot), now=now or self.now)

    def test_uncommitted_plan_cannot_release_text(self):
        self.assertFalse(self.plan['committed'])
        self.assertFalse(self.plan['send_authorized'])
        with self.assertRaisesRegex(e.LedgerError, 'not in the committed'):
            self.verify()
        with self.assertRaises(e.LedgerError):
            self.verify(snapshot=self.plan, observation=self.observe())

    def test_failed_commit_or_orphan_commit_keeps_output_blocked(self):
        with self.assertRaises(OSError):
            self.repo.commit(self.plan, fail=True)
        with self.assertRaises(e.LedgerError):
            self.verify()
        candidate = self.repo.snapshot()
        for change in self.plan['changes']:
            candidate['files'][change['path']] = change['content']
        candidate['head'] = 'f' * 40
        with self.assertRaisesRegex(e.LedgerError, 'HEAD differs'):
            self.verify(snapshot=candidate, observation=self.observe())

    def test_committed_readback_releases_exact_bytes_without_mutation(self):
        self.repo.commit(self.plan)
        before = self.repo.snapshot()
        result = self.verify()
        self.assertTrue(result['ready_to_send'])
        self.assertEqual(result['items'][0]['block'], self.op['items'][0]['block'])
        self.assertEqual(result['items'][0]['source'], 'Example')
        self.assertEqual(result['items'][0]['queue_status'], 'queued')
        self.assertEqual(result['verified_head'], self.repo.head)
        self.assertFalse(result['attachment_delivery_authorized'])
        self.assertEqual(before, self.repo.snapshot())

    def test_lost_commit_response_and_duplicate_retry_use_current_durable_operation(self):
        self.repo.commit(self.plan)
        self.assertTrue(e.plan(self.repo.snapshot(), self.op)['replayed'])
        self.assertTrue(self.verify()['ready_to_send'])
        self.repo.execute('receive', request_id='later')
        self.assertTrue(self.verify()['ready_to_send'])
        self.assertEqual(len(self.repo.state['records']), 1)

    def test_missing_observation_and_snapshot_binding_fail_closed(self):
        self.repo.commit(self.plan)
        for change in ({'repository': 'other/repo'}, {'branch': 'other'}, {'head': 'e' * 40},
                       {'snapshot_sha256': 'a' * 64}):
            with self.subTest(change=change), self.assertRaises(e.LedgerError):
                self.verify(observation={**self.observe(), **change})
        with self.assertRaises(e.LedgerError):
            gate.verify_intake_output(self.repo.snapshot(), self.op, None, now=self.now)

    def test_stale_and_future_readback_fail_closed(self):
        self.repo.commit(self.plan)
        for delta in (301, -1):
            with self.subTest(delta=delta), self.assertRaisesRegex(e.LedgerError, 'stale or future'):
                self.verify(now=self.now + timedelta(seconds=delta))

    def test_incomplete_snapshot_and_operation_mutation_blocked(self):
        self.repo.commit(self.plan)
        snapshot = self.repo.snapshot()
        snapshot['complete'] = False
        with self.assertRaises(e.LedgerError):
            self.verify(snapshot=snapshot)
        op = copy.deepcopy(self.op)
        op['items'][0]['block'] = block('Changed after commit')
        with self.assertRaisesRegex(e.LedgerError, 'operation differs'):
            self.verify(operation=op)
        with self.assertRaises(e.LedgerError):
            self.verify(operation={'kind': 'preview'})

    def test_modified_revision_and_result_mapping_fail_closed(self):
        self.repo.commit(self.plan)
        original = self.repo.snapshot()
        state = self.repo.state
        state['records'][0]['revisions'][0]['block'] = block('Tamper')
        self.repo.files[e.LEDGER] = e.encoded(state)
        with self.assertRaises(e.LedgerError):
            self.verify()
        self.repo.files = original['files']
        state = self.repo.state
        state['operations'][self.op['operation_id']]['result']['records'] = []
        self.repo.files[e.LEDGER] = e.encoded(state)
        with self.assertRaisesRegex(e.LedgerError, 'differs from resolved'):
            self.verify()

    def test_final_block_compare_survives_consistent_revision_hash_tampering(self):
        self.repo.commit(self.plan)
        state = self.repo.state
        rev = state['records'][0]['revisions'][0]
        rev.update(block=block('Tampered'), sha256=e.digest(block('Tampered')))
        state['requests']['intake']['records'][0]['sha256'] = rev['sha256']
        state['operations'][self.op['operation_id']]['result']['records'][0]['sha256'] = rev['sha256']
        self.repo.files[e.LEDGER] = e.encoded(state)
        with self.assertRaisesRegex(e.LedgerError, 'Final block differs'):
            self.verify()

    def test_correction_passes_but_prior_superseded_result_is_blocked(self):
        self.repo.commit(self.plan)
        self.repo.execute('receive', request_id='correction', corrects_record_id=1)
        correction = self.repo.operation('correct', request_id='correction', record_id=1,
                                        block=block('Corrected'), image_verified=True)
        self.repo.commit(e.plan(self.repo.snapshot(), correction))
        self.assertTrue(self.verify(operation=correction)['ready_to_send'])
        with self.assertRaisesRegex(e.LedgerError, 'superseded'):
            self.verify()

    def test_delivered_duplicate_is_labeled_delivered_not_queued(self):
        self.repo.commit(self.plan)
        batch = self.repo.published()
        self.repo.begin(batch)
        self.repo.acknowledge(batch)
        self.repo.execute('receive', request_id='duplicate')
        duplicate = self.repo.operation('finalize', request_id='duplicate', items=self.op['items'])
        self.repo.commit(e.plan(self.repo.snapshot(), duplicate))
        result = self.verify(operation=duplicate)
        self.assertTrue(result['ready_to_send'])
        self.assertEqual(result['items'][0]['queue_status'], 'delivered')
        self.assertEqual(len(self.repo.state['records']), 1)

    def test_cli_failure_overwrites_old_success_without_final_text(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / 'gate.json'
            output.write_text('{"ready_to_send": true, "items": ["old success"]}')
            run = subprocess.run([sys.executable, str(ROOT / 'intake_output_gate.py'), '--output', str(output)],
                input='{}', capture_output=True, text=True)
            self.assertEqual(run.returncode, 1)
            result = json.loads(output.read_text())
            self.assertFalse(result['ready_to_send'])
            self.assertEqual(result['items'], [])

    def test_remapped_correction_reference_is_blocked(self):
        self.repo.commit(self.plan)
        self.repo.execute('receive', request_id='correction', corrects_record_id=1)
        correction = self.repo.operation('correct', request_id='correction', record_id=1,
                                        block=block('Corrected'), image_verified=True)
        self.repo.commit(e.plan(self.repo.snapshot(), correction))
        state = self.repo.state
        state['records'][0]['id'] = 2
        state['next_id'] = 3
        for request in state['requests'].values():
            for ref in request.get('records', []):
                ref['id'] = 2
        state['operations'][self.op['operation_id']]['result']['records'][0]['id'] = 2
        state['operations'][correction['operation_id']]['result']['record']['id'] = 2
        self.repo.files[e.LEDGER] = e.encoded(state)
        with self.assertRaisesRegex(e.LedgerError, 'differs from target'):
            self.verify(operation=correction)

    def test_explicit_source_drift_is_blocked(self):
        self.repo.commit(self.plan)
        state = self.repo.state
        state['records'][0]['revisions'][0]['source'] = 'Altered'
        self.repo.files[e.LEDGER] = e.encoded(state)
        with self.assertRaisesRegex(e.LedgerError, 'Source differs'):
            self.verify()

    def test_freshness_boundary_and_cli_clock_override_fail_closed(self):
        self.repo.commit(self.plan)
        self.assertTrue(self.verify(now=self.now + timedelta(seconds=300))['ready_to_send'])
        observation = self.observe()
        observation['observed_at'] = (datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
        payload = {'snapshot': self.repo.snapshot(), 'operation': self.op, 'observation': observation,
                   'now': observation['observed_at']}
        run = subprocess.run([sys.executable, str(ROOT / 'intake_output_gate.py')],
            input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(run.returncode, 1)
        self.assertFalse(json.loads(run.stdout)['ready_to_send'])

    def test_standard_outer_whitespace_matches_engine_normalization(self):
        self.op['items'][0]['block'] = '\n' + self.op['items'][0]['block'] + '\n'
        self.repo.commit(e.plan(self.repo.snapshot(), self.op))
        self.assertEqual(self.verify()['items'][0]['block'], self.op['items'][0]['block'].strip())

    def test_trusted_route_preserves_exact_blank_field_bytes(self):
        self.repo.files[e.CONFIG] = e.encoded({'trusted_preprocessed_route_sha256': ['f' * 64],
            'compilation_enabled': True, 'cutover_confirmation_sha256': 'f' * 64})
        self.repo.commit(self.plan)
        self.repo.execute('receive', request_id='trusted', mode='trusted_preprocessed',
                          trusted_route_sha256='f' * 64)
        original = 'Title: \nURL: \nImage URL: \nSummary: '
        op = self.repo.operation('finalize', request_id='trusted', items=[{'block': original}])
        self.repo.commit(e.plan(self.repo.snapshot(), op))
        self.assertEqual(self.verify(operation=op)['items'][0]['block'], original)

    def test_cli_deep_json_replaces_old_success_with_blocked_result(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / 'gate.json'
            output.write_text('{"ready_to_send": true, "items": ["old success"]}')
            run = subprocess.run([sys.executable, str(ROOT / 'intake_output_gate.py'), '--output', str(output)],
                input='[' * 10000 + ']' * 10000, capture_output=True, text=True)
            self.assertEqual(run.returncode, 1)
            self.assertFalse(json.loads(output.read_text())['ready_to_send'])
            self.assertEqual(json.loads(output.read_text())['items'], [])

    def test_planner_status_replay_and_mutation_never_release_intake(self):
        self.assertFalse(self.plan['ready_to_send'])
        self.repo.commit(self.plan)
        for op in ({'kind': 'status'}, {'kind': 'preview'}, self.op):
            self.assertFalse(e.plan(self.repo.snapshot(), op)['ready_to_send'])

    def test_cli_success_uses_real_clock_not_payload_override(self):
        self.repo.commit(self.plan)
        observation = self.observe()
        observation['observed_at'] = datetime.now(timezone.utc).isoformat()
        payload = {'snapshot': self.repo.snapshot(), 'operation': self.op, 'observation': observation,
                   'now': T}
        # The synthetic operation clock can be ahead of actual system time in
        # isolated environments; use a self-contained historical test fixture.
        observed = datetime.fromisoformat(observation['observed_at'])
        if observed < self.now:
            self.skipTest('System clock precedes synthetic fixture')
        run = subprocess.run([sys.executable, str(ROOT / 'intake_output_gate.py')],
            input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout)
        self.assertTrue(json.loads(run.stdout)['ready_to_send'])


if __name__ == '__main__':
    unittest.main()
