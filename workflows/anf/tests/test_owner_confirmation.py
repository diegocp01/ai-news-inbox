import copy
import unittest
from test_ledger_engine import Repository, e, T, HASH

class OwnerConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.r=Repository().initialize(); self.r.add(); self.b=self.r.published(); self.r.begin(self.b)
        batch=self.r.state['batches'][self.b]
        self.op=self.r.operation('confirm_owner_delivery', batch_id=self.b, attempt_id='attempt_1',
            expected_batch_sha256=e.digest(e.canonical(batch)), confirmation_at=T,
            authorization_sha256=HASH, confirmed_content_sha256=batch['txt_sha256'],
            reason_code='explicit_owner_confirmed_receipt')

    def test_confirm_preserves_history_and_replay(self):
        before=self.r.state['batches'][self.b]; p=e.plan(self.r.snapshot(),self.op); self.r.commit(p)
        s=self.r.state; b=s['batches'][self.b]
        self.assertEqual(s['checkpoint'],1); self.assertIsNone(s['pending_batch_id'])
        self.assertEqual(b['owner_confirmation']['previous_delivery'],before['delivery'])
        self.assertNotIn('receipt',b['delivery']['attempts'][-1])
        self.assertFalse(p['result']['native_receipt_verified'])
        self.assertEqual(e.plan(self.r.snapshot(),self.op)['changes'],[])
        self.r.add('Next'); next_id=self.r.published(); self.assertNotEqual(next_id,self.b)
        self.r.begin(next_id,'next'); self.r.acknowledge(next_id,'next')
        self.assertEqual(self.r.state['checkpoint'],2)

    def test_equivalent_timestamp_formats(self):
        for at in ('2026-09-30T15:00:00Z', '2026-09-30T15:00:00.000000+00:00'):
            p=e.plan(self.r.snapshot(),{**self.op,'at':at})
            self.assertEqual(p['result']['checkpoint'],1)

    def test_bad_scope_or_proof_fails(self):
        for key,value in [('expected_batch_sha256','0'*64),('confirmed_content_sha256','0'*64),
                          ('attempt_id','wrong'),('authorization_sha256',''),('authorization_sha256','0'*64),
                          ('confirmation_at','1900-01-01T00:00:00+00:00'),
                          ('confirmation_at','2099-01-01T00:00:00+00:00'),('reason_code','automatic')]:
            op={**self.op,key:value}
            with self.subTest(key=key), self.assertRaises(e.LedgerError): e.plan(self.r.snapshot(),op)
        with self.assertRaises(e.LedgerError): e.plan(self.r.snapshot(),{**self.op,'accepted':True})

    def test_native_path_still_requires_receipt(self):
        with self.assertRaises(e.LedgerError): self.r.execute('acknowledge',batch_id=self.b,attempt_id='attempt_1')

    def test_tamper_rejected(self):
        self.r.commit(e.plan(self.r.snapshot(),self.op))
        for field in ('expected_batch_sha256','authorization_sha256'):
            s=self.r.snapshot(); st=self.r.state
            st['batches'][self.b]['owner_confirmation']['operation'][field]='0'*64
            s['files'][e.LEDGER]=e.encoded(st)
            with self.assertRaises(e.LedgerError): e.plan(s,{'kind':'status'})

    def test_failed_save_retries_same_operation(self):
        p=e.plan(self.r.snapshot(),self.op)
        with self.assertRaises(OSError): self.r.commit(p,fail=True)
        self.r.commit(e.plan(self.r.snapshot(),self.op))
        self.assertEqual(self.r.state['checkpoint'],1)

if __name__=='__main__': unittest.main()
