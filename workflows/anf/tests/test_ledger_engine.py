import copy
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ledger_engine', ROOT / 'ledger_engine.py')
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)
T = '2026-09-30T15:00:00+00:00'
HASH = 'f' * 64


def block(title='Example launch', url='https://example.com/news', image='https://example.com/image.png', summary='An example company announces an AI feature.'):
    return f'Title: {title}\nURL: {url}\nImage URL: {image}\nSummary: {summary}'


class Repository:
    """Isolated atomic CAS simulation. Never invokes git, a network or external send."""
    def __init__(self):
        self.head = '0' * 40
        self.files = {e.POLICY: (ROOT / 'policy.json').read_text(), e.CONFIG: e.encoded({
            'trusted_preprocessed_route_sha256': [], 'compilation_enabled': True, 'cutover_confirmation_sha256': HASH})}
        self.seq = 0
        self.ops = 0

    def snapshot(self):
        return {'head': self.head, 'complete': True, 'files': copy.deepcopy(self.files)}

    def commit(self, plan, fail=False):
        if fail:
            raise OSError('synthetic save failure')
        if plan['base_sha'] != self.head:
            raise e.LedgerError('CAS conflict')
        if not plan['changes']:
            return
        candidate = copy.deepcopy(self.files)
        for item in plan['changes']:
            candidate[item['path']] = item['content']
        self.seq += 1
        self.head = f'{self.seq:040x}'
        self.files = candidate

    def operation(self, kind, **kwargs):
        self.ops += 1
        return {'kind': kind, 'at': T, 'operation_id': f'op_{self.ops}', **kwargs}

    def execute(self, kind, **kwargs):
        plan = e.plan(self.snapshot(), self.operation(kind, **kwargs))
        self.commit(plan)
        return plan['result']

    @property
    def state(self):
        return json.loads(self.files[e.LEDGER])

    def initialize(self):
        self.execute('initialize', boundary_evidence_sha256=HASH)
        return self

    def add(self, title='Example launch', request=None, **kwargs):
        request = request or f'request_{self.ops}'
        self.execute('receive', request_id=request)
        return self.execute('finalize', request_id=request,
                            items=[{'block': block(title, **kwargs), 'image_verified': True}])

    def prepared(self):
        return self.execute('prepare')['batch']['batch_id']

    def published(self):
        batch_id = self.prepared()
        self.execute('publish', batch_id=batch_id)
        return batch_id

    def begin(self, batch_id, attempt='attempt_1'):
        return self.execute('begin_delivery', batch_id=batch_id, attempt_id=attempt, target_sha256=HASH)

    def receipt(self, batch_id, **overrides):
        return {'channel': 'chatgpt', 'accepted': True, 'accepted_at': T,
                'attachment_sha256': self.state['batches'][batch_id]['txt_sha256'],
                'target_sha256': HASH, 'message_receipt_sha256': 'e' * 64,
                'native_attachment_receipt_sha256': 'd' * 64, **overrides}

    def acknowledge(self, batch_id, attempt='attempt_1', **overrides):
        return self.execute('acknowledge', batch_id=batch_id, attempt_id=attempt,
                            receipt=self.receipt(batch_id, **overrides))


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository().initialize()

    def test_weekend_items_have_no_daily_reset(self):
        self.repo = Repository()
        self.repo.execute('initialize', boundary_evidence_sha256=HASH, at='2026-09-24T00:00:00+00:00')
        for i, day in enumerate(('2026-09-25', '2026-09-26', '2026-09-27', '2026-09-28')):
            request_id = f'day_{i}'
            self.repo.execute('receive', request_id=request_id, at=day + 'T10:00:00+00:00')
            self.repo.execute('finalize', request_id=request_id, at=day + 'T10:01:00+00:00',
                              items=[{'block': block(str(i)), 'image_verified': True}])
        prepared = self.repo.execute('prepare')
        self.assertEqual(prepared['batch']['count'], 4)
        self.assertEqual([r['id'] for r in prepared['batch']['records']], [1, 2, 3, 4])

    def test_exact_duplicate_in_full_delivered_history(self):
        self.repo.add()
        batch = self.repo.published()
        self.repo.begin(batch)
        self.repo.acknowledge(batch)
        result = self.repo.add()
        self.assertEqual(result['duplicates'][0]['id'], 1)
        self.assertEqual(self.repo.state['next_id'], 2)
        self.assertEqual(self.repo.execute('prepare')['status'], 'empty')

    def test_monotonic_ids_after_delivery_and_duplicates(self):
        self.repo.add('One')
        self.repo.add('One')
        self.repo.add('Two')
        self.assertEqual([r['id'] for r in self.repo.state['records']], [1, 2])

    def test_correction_keeps_provenance_and_supersedes_only_unpublished_batch(self):
        self.repo.add('Old')
        old_batch = self.repo.prepared()
        old_txt = self.repo.files[self.repo.state['batches'][old_batch]['txt_path']]
        self.repo.execute('receive', request_id='correction', corrects_record_id=1)
        self.repo.execute('correct', request_id='correction', record_id=1,
                          block=block('Corrected'), image_verified=True)
        self.assertEqual(len(self.repo.state['records'][0]['revisions']), 2)
        self.assertEqual(self.repo.state['batches'][old_batch]['status'], 'superseded')
        new_batch = self.repo.prepared()
        self.assertNotEqual(old_batch, new_batch)
        self.assertEqual(old_txt, self.repo.files[self.repo.state['batches'][old_batch]['txt_path']])
        self.assertEqual(self.repo.state['batches'][new_batch]['count'], 1)

    def test_superseded_exact_duplicate_never_requeues(self):
        self.repo.add('Old')
        self.repo.execute('receive', request_id='correction', corrects_record_id=1)
        self.repo.execute('correct', request_id='correction', record_id=1,
                          block=block('Corrected'), image_verified=True)
        result = self.repo.add('Old')
        self.assertTrue(result['duplicates'][0]['superseded'])
        self.assertEqual(self.repo.state['next_id'], 2)
        self.assertIn('Corrected', self.repo.state['records'][0]['revisions'][-1]['block'])

    def test_correction_of_published_record_rejected(self):
        self.repo.add('Original')
        batch = self.repo.published()
        self.repo.execute('receive', request_id='correction', corrects_record_id=1)
        before = self.repo.snapshot()
        with self.assertRaisesRegex(e.LedgerError, 'published'):
            self.repo.execute('correct', request_id='correction', record_id=1,
                              block=block('New'), image_verified=True)
        self.assertEqual(before, self.repo.snapshot())
        self.assertEqual(self.repo.state['batches'][batch]['status'], 'published')

    def test_new_arrivals_excluded_from_pending_and_checkpoint(self):
        self.repo.add('One')
        batch = self.repo.prepared()
        txt = self.repo.files[self.repo.state['batches'][batch]['txt_path']]
        self.repo.add('Two')
        retry = self.repo.execute('prepare')
        self.assertTrue(retry['retry'])
        self.assertEqual(retry['batch']['batch_id'], batch)
        self.assertEqual(retry['batch']['count'], 1)
        self.repo.execute('publish', batch_id=batch)
        self.repo.begin(batch)
        self.repo.acknowledge(batch)
        self.assertEqual(self.repo.state['checkpoint'], 1)
        self.assertEqual(self.repo.execute('prepare')['batch']['first_id'], 2)
        self.assertEqual(self.repo.files[self.repo.state['batches'][batch]['txt_path']], txt)

    def test_unresolved_intake_blocks_new_prepare_but_not_frozen_retry(self):
        self.repo.add()
        self.repo.execute('receive', request_id='failed_request')
        with self.assertRaisesRegex(e.LedgerError, 'Unresolved intakes'):
            self.repo.execute('prepare')
        self.repo.execute('reconcile_intake', request_id='failed_request', record_ids=[1], evidence_sha256=HASH)
        batch = self.repo.prepared()
        self.repo.execute('receive', request_id='later_unresolved')
        self.assertEqual(self.repo.execute('prepare')['batch']['batch_id'], batch)
        self.repo.execute('publish', batch_id=batch)
        self.repo.begin(batch)
        self.repo.acknowledge(batch)
        with self.assertRaisesRegex(e.LedgerError, 'Unresolved intakes'):
            self.repo.execute('prepare')

    def test_declared_pending_correction_blocks_frozen_delivery(self):
        self.repo.add()
        batch = self.repo.prepared()
        self.repo.execute('receive', request_id='correction', corrects_record_id=1)
        with self.assertRaisesRegex(e.LedgerError, 'Unresolved intakes'):
            self.repo.execute('publish', batch_id=batch)

    def test_finalize_preserves_receive_provenance_and_uses_completion_order(self):
        self.repo.execute('receive', request_id='first')
        first = copy.deepcopy(self.repo.state['requests']['first'])
        self.repo.execute('receive', request_id='second')
        self.repo.execute('finalize', request_id='second', items=[{'block': block('Second'), 'image_verified': True}])
        self.assertEqual(self.repo.state['requests']['first'], first)
        self.repo.execute('finalize', request_id='first', items=[{'block': block('First'), 'image_verified': True}])
        self.assertIn('Second', self.repo.state['records'][0]['revisions'][0]['block'])
        self.assertIn('First', self.repo.state['records'][1]['revisions'][0]['block'])
        self.assertEqual(self.repo.state['requests']['first']['received_sequence'], 1)
        self.assertEqual(self.repo.state['requests']['second']['received_sequence'], 2)

    def test_reconciliation_cannot_drop_expected_items(self):
        self.repo.add()
        self.repo.execute('receive', request_id='multi', expected_items=3)
        with self.assertRaisesRegex(e.LedgerError, 'every expected item'):
            self.repo.execute('reconcile_intake', request_id='multi', record_ids=[1], evidence_sha256=HASH)
        self.repo.execute('reconcile_intake', request_id='multi', record_ids=[1, 1, 1], evidence_sha256=HASH)
        self.assertEqual(len(self.repo.state['requests']['multi']['records']), 3)

    def test_correction_retains_frozen_membership_when_later_items_arrive(self):
        self.repo.add('Original')
        batch = self.repo.prepared()
        self.repo.add('Later')
        self.repo.execute('receive', request_id='correction', corrects_record_id=1)
        self.repo.execute('correct', request_id='correction', record_id=1,
                          block=block('Corrected'), image_verified=True)
        replacement = self.repo.execute('prepare')['batch']
        self.assertNotEqual(replacement['batch_id'], batch)
        self.assertEqual([ref['id'] for ref in replacement['records']], [1])
        self.repo.execute('publish', batch_id=replacement['batch_id'])
        self.repo.begin(replacement['batch_id'])
        self.repo.acknowledge(replacement['batch_id'])
        self.assertEqual(self.repo.execute('prepare')['batch']['first_id'], 2)

    def test_partial_multi_item_failure_is_atomic(self):
        self.repo.execute('receive', request_id='multiple', expected_items=2)
        before = self.repo.snapshot()
        with self.assertRaises(e.LedgerError):
            self.repo.execute('finalize', request_id='multiple', items=[
                {'block': block('valid'), 'image_verified': True}, {'block': 'invalid'}])
        self.assertEqual(before, self.repo.snapshot())
        self.assertEqual(self.repo.state['requests']['multiple']['status'], 'received')

    def test_failed_commit_is_visible_and_no_save_or_checkpoint(self):
        self.repo.add()
        plan = e.plan(self.repo.snapshot(), self.repo.operation('prepare'))
        before = self.repo.snapshot()
        self.assertFalse(plan['committed'])
        with self.assertRaises(OSError):
            self.repo.commit(plan, fail=True)
        self.assertEqual(before, self.repo.snapshot())
        self.assertEqual(self.repo.state['checkpoint'], 0)

    def test_concurrent_writer_cas_conflict_then_replan(self):
        snapshot = self.repo.snapshot()
        op_a = self.repo.operation('receive', request_id='a')
        op_b = self.repo.operation('receive', request_id='b')
        plan_a = e.plan(snapshot, op_a)
        plan_b = e.plan(snapshot, op_b)
        self.repo.commit(plan_a)
        with self.assertRaisesRegex(e.LedgerError, 'CAS'):
            self.repo.commit(plan_b)
        self.repo.commit(e.plan(self.repo.snapshot(), op_b))
        self.assertEqual(set(self.repo.state['requests']), {'a', 'b'})

    def test_filename_collision_and_metadata_are_one_atomic_plan(self):
        self.repo.add()
        batch = self.repo.prepared()
        for suffix in ['', '-2']:
            self.repo.files[f'items/2026-09-30{suffix}.json'] = '[]\n'
        plan = e.plan(self.repo.snapshot(), self.repo.operation('publish', batch_id=batch))
        self.assertEqual({c['path'] for c in plan['changes']}, {'items/2026-09-30-3.json', e.LEDGER})
        self.assertIsNone(self.repo.state['batches'][batch].get('publication'))
        self.repo.commit(plan)
        self.assertEqual(self.repo.state['batches'][batch]['publication']['path'], 'items/2026-09-30-3.json')
        self.repo.execute('publish', batch_id=batch)
        self.assertNotIn('items/2026-09-30-4.json', self.repo.files)

    def test_publication_plan_cas_race_rechooses_filename(self):
        self.repo.add()
        batch = self.repo.prepared()
        op = self.repo.operation('publish', batch_id=batch)
        stale = e.plan(self.repo.snapshot(), op)
        self.repo.commit({'base_sha': self.repo.head, 'changes': [{'path': 'items/2026-09-30.json', 'content': '[]\n'}]})
        with self.assertRaises(e.LedgerError):
            self.repo.commit(stale)
        fresh = e.plan(self.repo.snapshot(), op)
        self.repo.commit(fresh)
        self.assertEqual(self.repo.state['batches'][batch]['publication']['path'], 'items/2026-09-30-2.json')

    def test_txt_exact_separator_trailer_and_json_schema(self):
        self.repo.add('One', url='https://www.reuters.com/news')
        self.repo.add('Two')
        batch_id = self.repo.prepared()
        batch = self.repo.state['batches'][batch_id]
        txt = self.repo.files[batch['txt_path']]
        expected = block('One', url='https://www.reuters.com/news') + '\n\n' + block('Two') + '\n\n\n\n\n\n.'
        self.assertEqual(txt, expected)
        self.assertFalse(txt.endswith('.\n'))
        items = json.loads(self.repo.files[batch['json_path']])
        self.assertEqual(set(items[0]), {'title', 'description', 'image_url', 'learn_more_url', 'date', 'source'})
        self.assertEqual(items[0]['source'], 'Reuters')
        self.assertEqual(items[0]['date'], '2026-09-30')

    def test_wrong_timezone_rejected(self):
        with self.assertRaisesRegex(e.LedgerError, 'UTC'):
            self.repo.execute('receive', request_id='badtime', at='2026-09-30T01:00:00-04:00')

    def test_policy_exact_subdomain_suffix_and_deceptive_host(self):
        policy = json.loads(self.repo.files[e.POLICY])
        for url in ('https://help.openai.com/a', 'https://OPENAI.COM./a', 'https://x.ai/a',
                    'https://a.b.ai/a', 'https://huggingface.co/m', 'https://hf.co/m'):
            with self.subTest(url=url), self.assertRaises(e.LedgerError):
                e.validate_block(block(url=url), policy, image_verified=True)
        e.validate_block(block(url='https://notopenai.com/news'), policy, image_verified=True)
        e.validate_block(block(url=''), policy, image_verified=True)
        for image in ('https://pbs.twimg.com/image', 'https://a.twimg.com/image', 'placeholder'):
            with self.subTest(image=image), self.assertRaises(e.LedgerError):
                e.validate_block(block(image=image), policy, image_verified=True)
        with self.assertRaisesRegex(e.LedgerError, 'word'):
            e.validate_block(block(summary=' '.join(['word'] * 61)), policy, image_verified=True)
        with self.assertRaisesRegex(e.LedgerError, 'verified'):
            e.validate_block(block(), policy)

    def test_trusted_preprocessed_fields_not_rewritten(self):
        original = 'Title: \nURL: https://openai.com/test\nImage URL: \nSummary: '
        self.repo.files[e.CONFIG] = e.encoded({'trusted_preprocessed_route_sha256': [HASH], 'compilation_enabled': True, 'cutover_confirmation_sha256': HASH})
        self.repo.execute('receive', request_id='trusted', mode='trusted_preprocessed', trusted_route_sha256=HASH)
        self.repo.execute('finalize', request_id='trusted', items=[{'block': original}])
        self.assertEqual(self.repo.state['records'][0]['revisions'][0]['block'], original)

    def test_publish_before_send_and_receipt_before_checkpoint(self):
        self.repo.add()
        batch = self.repo.prepared()
        with self.assertRaisesRegex(e.LedgerError, 'GitHub'):
            self.repo.begin(batch)
        self.repo.execute('publish', batch_id=batch)
        self.repo.begin(batch)
        for overrides in ({'accepted': False}, {'attachment_sha256': HASH}, {'message_receipt_sha256': ''},
                          {'native_attachment_receipt_sha256': ''}, {'target_sha256': 'a' * 64}):
            with self.subTest(overrides=overrides), self.assertRaises(e.LedgerError):
                self.repo.acknowledge(batch, **overrides)
        self.assertEqual(self.repo.state['checkpoint'], 0)
        self.repo.acknowledge(batch)
        self.assertEqual(self.repo.state['checkpoint'], 1)

    def test_uncertain_delivery_forbids_blind_retry_and_can_reconcile_accepted(self):
        self.repo.add()
        batch = self.repo.published()
        self.repo.begin(batch)
        self.repo.execute('delivery_uncertain', batch_id=batch, attempt_id='attempt_1', evidence_sha256=HASH)
        with self.assertRaisesRegex(e.LedgerError, 'reconcile'):
            self.repo.begin(batch, 'attempt_2')
        with self.assertRaisesRegex(e.LedgerError, 'reconciliation'):
            self.repo.execute('delivery_failed', batch_id=batch, attempt_id='attempt_1',
                              evidence_sha256=HASH, definitely_not_accepted=True)
        self.repo.acknowledge(batch)
        self.assertEqual(self.repo.state['checkpoint'], 1)

    def test_inflight_crash_cannot_resend_until_not_sent_reconciled(self):
        self.repo.add()
        batch = self.repo.published()
        self.repo.begin(batch)
        with self.assertRaises(e.LedgerError):
            self.repo.begin(batch, 'attempt_2')
        self.repo.execute('reconcile_not_sent', batch_id=batch, attempt_id='attempt_1', evidence_sha256=HASH)
        self.repo.begin(batch, 'attempt_2')
        self.repo.acknowledge(batch, 'attempt_2')
        self.assertEqual(len(self.repo.state['batches'][batch]['delivery']['attempts']), 2)

    def test_confirmed_delivery_failure_keeps_same_batch_and_publication(self):
        self.repo.add()
        batch = self.repo.published()
        path = self.repo.state['batches'][batch]['publication']['path']
        self.repo.begin(batch)
        self.repo.execute('delivery_failed', batch_id=batch, attempt_id='attempt_1',
                          evidence_sha256=HASH, definitely_not_accepted=True)
        self.assertEqual(self.repo.state['checkpoint'], 0)
        self.assertEqual(self.repo.state['pending_batch_id'], batch)
        self.repo.begin(batch, 'attempt_2')
        self.repo.acknowledge(batch, 'attempt_2')
        self.assertEqual(self.repo.state['batches'][batch]['publication']['path'], path)

    def test_idempotent_op_replay_and_conflicting_reuse(self):
        op = self.repo.operation('receive', request_id='a')
        plan = e.plan(self.repo.snapshot(), op)
        self.repo.commit(plan)
        replay = e.plan(self.repo.snapshot(), op)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['changes'], [])
        with self.assertRaisesRegex(e.LedgerError, 'reused'):
            e.plan(self.repo.snapshot(), {**op, 'request_id': 'b'})

    def test_missing_or_altered_immutable_artifact_fails_closed(self):
        self.repo.add()
        batch = self.repo.prepared()
        path = self.repo.state['batches'][batch]['txt_path']
        self.repo.files[path] += '\n'
        with self.assertRaisesRegex(e.LedgerError, 'artifact'):
            self.repo.execute('prepare')

    def test_published_file_drift_blocks_acknowledgment(self):
        self.repo.add()
        batch = self.repo.published()
        self.repo.begin(batch)
        self.repo.files[self.repo.state['batches'][batch]['publication']['path']] = '[]\n'
        with self.assertRaisesRegex(e.LedgerError, 'Published item'):
            self.repo.acknowledge(batch)

    def test_state_recovery_from_git_snapshot_only(self):
        self.repo.add('Persisted')
        batch = self.repo.published()
        serialized = json.dumps(self.repo.snapshot())
        restored = json.loads(serialized)
        result = e.plan(restored, {'kind': 'status'})['result']
        self.assertEqual(result['pending_batch_id'], batch)
        self.assertEqual(result['queued_count'], 1)

    def test_import_is_byte_preserving_and_fail_closed_until_reconciled(self):
        repo = Repository()
        imported = {'id': 12, 'created_at': '2026-09-20T12:00:00+00:00',
                    'block': block(url='https://openai.com/legacy'), 'source': 'Historical source'}
        imported['sha256'] = e.digest(imported['block'])
        repo.execute('import_archive', records=[imported], checkpoint=0,
                     archive_sha256=HASH, checkpoint_document_sha256=HASH)
        self.assertEqual(repo.state['records'][0]['revisions'][0]['block'], imported['block'])
        self.assertEqual(repo.state['next_id'], 13)
        with self.assertRaisesRegex(e.LedgerError, 'Migration'):
            repo.execute('prepare')
        repo.execute('reconcile_migration', checkpoint=0, evidence_sha256=HASH)
        self.assertEqual(repo.execute('prepare')['batch']['count'], 1)
        self.assertEqual(len(repo.state['checkpoint_history']), 2)

    def test_incomplete_snapshot_rejected_and_preview_read_only(self):
        snapshot = self.repo.snapshot()
        snapshot['complete'] = False
        with self.assertRaisesRegex(e.LedgerError, 'complete'):
            e.plan(snapshot, {'kind': 'status'})
        self.repo.add()
        before = self.repo.snapshot()
        plan = e.plan(before, {'kind': 'preview'})
        self.assertEqual(plan['changes'], [])
        self.assertEqual(len(plan['result']['items']), 1)
        self.assertEqual(before, self.repo.snapshot())

    def test_cli_failure_exits_nonzero_and_reports_not_saved(self):
        result = subprocess.run([sys.executable, str(ROOT / 'ledger_engine.py')], input='{}', text=True,
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)['saved'])

    def test_determinism(self):
        snapshot = self.repo.snapshot()
        op = self.repo.operation('receive', request_id='a')
        self.assertEqual(e.plan(snapshot, op), e.plan(snapshot, op))

    def test_tampered_batch_boundaries_rejected(self):
        self.repo.add('One')
        batch = self.repo.published()
        self.repo.add('Two')
        state = self.repo.state
        state['batches'][batch]['last_id'] = 2
        self.repo.files[e.LEDGER] = e.encoded(state)
        with self.assertRaisesRegex(e.LedgerError, 'boundary'):
            self.repo.begin(batch)

    def test_migration_cannot_ack_post_import_intake(self):
        repo = Repository()
        record = {'id': 12, 'created_at': T, 'block': block('Legacy'), 'source': ''}
        record['sha256'] = e.digest(record['block'])
        repo.execute('import_archive', records=[record], checkpoint=0,
                     archive_sha256=HASH, checkpoint_document_sha256=HASH)
        repo.add('New')
        with self.assertRaisesRegex(e.LedgerError, 'post-import'):
            repo.execute('reconcile_migration', checkpoint=13, evidence_sha256=HASH)

    def test_delivery_intent_replay_explicitly_forbids_send(self):
        self.repo.add()
        batch = self.repo.published()
        op = self.repo.operation('begin_delivery', batch_id=batch, attempt_id='a', target_sha256=HASH)
        self.repo.commit(e.plan(self.repo.snapshot(), op))
        replay = e.plan(self.repo.snapshot(), op)
        self.assertFalse(replay['send_authorized'])
        self.assertEqual(replay['result']['status'], 'operation_replayed')

    def test_encoded_and_unicode_dot_hosts_cannot_bypass_policy(self):
        policy = json.loads(self.repo.files[e.POLICY])
        for url in ('https://openai%2ecom/news', 'https://openai.com。/news', 'https://a.ai。/news',
                    'https://openai.com\\@example.com/news'):
            with self.subTest(url=url), self.assertRaises(e.LedgerError):
                e.validate_block(block(url=url), policy, image_verified=True)
        with self.assertRaises(e.LedgerError):
            e.validate_block(block(image='https://pbs.twimg.com。/image'), policy, image_verified=True)

    def test_source_only_correction_preserves_revision(self):
        self.repo.add()
        self.repo.execute('receive', request_id='source_correction', corrects_record_id=1)
        self.repo.execute('correct', request_id='source_correction', record_id=1,
                          block=block(), source='Correct publisher', image_verified=True)
        revisions = self.repo.state['records'][0]['revisions']
        self.assertEqual(len(revisions), 2)
        self.assertEqual(revisions[-1]['source'], 'Correct publisher')

    def test_imported_exports_immutable_and_suffix_ten_valid(self):
        repo = Repository()
        record = {'id': 1, 'created_at': T, 'block': block(), 'source': ''}
        record['sha256'] = e.digest(record['block'])
        repo.execute('import_archive', records=[record], checkpoint=1,
                     archive_sha256=HASH, checkpoint_document_sha256=HASH,
                     legacy_checkpoint_metadata={'last_github_filename': 'items/2026-09-30-10.json'},
                     legacy_exports={'ANFs_pending_1-1_abcdef.txt': block() + '\n'})
        path = repo.state['checkpoint_history'][0]['imported_exports'][0]['path']
        self.assertEqual(repo.files[path], block() + '\n')
        repo.files[path] += '.'
        with self.assertRaisesRegex(e.LedgerError, 'historical export'):
            repo.execute('reconcile_migration', checkpoint=1, evidence_sha256=HASH)

    def test_nonobject_finalize_cli_reports_structured_failure(self):
        self.repo.execute('receive', request_id='bad')
        payload = {'snapshot': self.repo.snapshot(),
                   'operation': self.repo.operation('finalize', request_id='bad', items=['bad'])}
        result = subprocess.run([sys.executable, str(ROOT / 'ledger_engine.py')], input=json.dumps(payload),
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)['saved'])

    def test_trusted_route_disabled_by_default_and_summary_bound_always_enforced(self):
        with self.assertRaisesRegex(e.LedgerError, 'disabled'):
            self.repo.execute('receive', request_id='trusted', mode='trusted_preprocessed', trusted_route_sha256=HASH)
        self.repo.files[e.CONFIG] = e.encoded({'trusted_preprocessed_route_sha256': [HASH], 'compilation_enabled': True, 'cutover_confirmation_sha256': HASH})
        self.repo.execute('receive', request_id='trusted', mode='trusted_preprocessed', trusted_route_sha256=HASH)
        with self.assertRaisesRegex(e.LedgerError, 'word limit'):
            self.repo.execute('finalize', request_id='trusted', items=[{'block': block(summary=' '.join(['word'] * 61))}])

    def test_future_receipt_and_backdated_operation_rejected(self):
        self.repo.add()
        batch = self.repo.published()
        self.repo.begin(batch)
        with self.assertRaisesRegex(e.LedgerError, 'future'):
            self.repo.acknowledge(batch, accepted_at='2100-01-01T00:00:00+00:00')
        with self.assertRaisesRegex(e.LedgerError, 'predates committed'):
            self.repo.execute('receive', request_id='backdated', at='2026-09-29T00:00:00+00:00')

    def test_corrections_require_declared_target_and_ingress_order(self):
        self.repo.add('Initial')
        self.repo.execute('receive', request_id='undeclared')
        with self.assertRaisesRegex(e.LedgerError, 'target'):
            self.repo.execute('correct', request_id='undeclared', record_id=1,
                              block=block('Forbidden'), image_verified=True)
        self.repo.execute('reconcile_intake', request_id='undeclared', record_ids=[1], evidence_sha256=HASH)
        self.repo.execute('receive', request_id='c1', corrects_record_id=1)
        self.repo.execute('receive', request_id='c2', corrects_record_id=1)
        with self.assertRaisesRegex(e.LedgerError, 'earlier received'):
            self.repo.execute('correct', request_id='c2', record_id=1, block=block('Later'), image_verified=True)
        self.repo.execute('correct', request_id='c1', record_id=1, block=block('Earlier'), image_verified=True)
        self.repo.execute('correct', request_id='c2', record_id=1, block=block('Later'), image_verified=True)
        self.assertIn('Later', self.repo.state['records'][0]['revisions'][-1]['block'])

    def test_supplemental_migration_provenance_and_reconciled_pending(self):
        repo = Repository()
        records = []
        for rid in range(1, 5):
            value = block(f'Imported {rid}')
            records.append({'id': rid, 'created_at': T, 'block': value, 'sha256': e.digest(value), 'source': ''})
        repo.execute('import_archive', records=records, checkpoint=1, archive_sha256=HASH,
                     checkpoint_document_sha256=HASH, record_provenance={
                         '2': {'kind': 'public_repository_reconstruction', 'evidence_sha256': HASH,
                               'github_path': 'items/2026-09-30.json', 'github_item_index': 11,
                               'github_commit': 'a' * 40},
                         '3': {'kind': 'user_confirmed_postcompile', 'evidence_sha256': HASH},
                         '4': {'kind': 'user_confirmed_postcompile', 'evidence_sha256': HASH}})
        self.assertEqual(repo.state['checkpoint_history'][0]['checkpoint'], 1)
        self.assertEqual(repo.state['records'][1]['revisions'][0]['mode'], 'public_repository_reconstruction')
        repo.execute('reconcile_migration', checkpoint=2, evidence_sha256=HASH)
        batch = repo.execute('prepare')['batch']
        self.assertEqual([ref['id'] for ref in batch['records']], [3, 4])
        self.assertEqual(repo.state['records'][2]['revisions'][0]['provenance']['kind'], 'user_confirmed_postcompile')

    def test_non_lf_line_separators_rejected(self):
        policy = json.loads(self.repo.files[e.POLICY])
        for separator in ('\r', '\u2028', '\u2029', '\x85', '\v', '\f'):
            with self.subTest(separator=repr(separator)), self.assertRaises(e.LedgerError):
                e.validate_block(block(summary='First' + separator + 'Second'), policy, image_verified=True)

    def test_forward_only_seed_and_cutover_compile_gate(self):
        repo = Repository()
        repo.files[e.CONFIG] = e.encoded({'trusted_preprocessed_route_sha256': [],
            'compilation_enabled': False, 'cutover_confirmation_sha256': None})
        repo.execute('initialize', boundary_evidence_sha256=HASH, seed_evidence_sha256=HASH,
                     initial_items=[{'block': block('Seed one'), 'source': 'One'}, {'block': block('Seed two'), 'source': 'Two'}])
        self.assertEqual([r['id'] for r in repo.state['records']], [1, 2])
        self.assertEqual(repo.state['checkpoint'], 0)
        self.assertEqual(repo.state['checkpoint_history'], [])
        with self.assertRaisesRegex(e.LedgerError, 'cutover'):
            repo.execute('prepare')
        repo.add('Next')
        self.assertEqual([r['received_sequence'] for r in repo.state['requests'].values()], [1, 2, 3])
        repo.files[e.CONFIG] = e.encoded({'trusted_preprocessed_route_sha256': [],
            'compilation_enabled': True, 'cutover_confirmation_sha256': HASH})
        self.assertEqual(repo.execute('prepare')['batch']['count'], 3)


if __name__ == '__main__':
    unittest.main()
