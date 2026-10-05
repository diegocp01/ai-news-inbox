"""Production v2 export checks; synthetic evidence is never real network proof."""
import copy
import json
import unittest
from test_ledger_engine import Repository, ROOT, HASH, T, block, e


def review(content, technical=False, basis=None):
    _, f = e.block_fields(content)
    def checked(url):
        return {'url': url, 'final_url': url, 'redirect_chain': [url], 'checked_at': T,
                'status': 'accessible_here', 'chase_status': 'unknown', 'evidence_sha256': HASH}
    article = checked(f['learn_more_url']) if f['learn_more_url'] else {
        'url': '', 'checked_at': T, 'status': 'blank_no_compliant_source', 'evidence_sha256': HASH}
    article['same_event'] = True
    image = {**checked(f['image_url']), 'content_type': 'image/png', 'width': 1200, 'height': 630,
             'pixels_inspected': True, 'image_bytes_sha256': HASH, 'relevance': 'story_specific',
             'relevance_note': 'Synthetic test depicts the exact feature covered by the story.'}
    return {'audience': {'decision': 'technical' if technical else 'general',
                        'basis': basis or ('developer_tool' if technical else 'general'),
                        'rationale': 'Synthetic test evidence describes the intended audience.', 'evidence_sha256': HASH},
            'quality': {'article': article, 'image': image}}


class EditorialTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository().initialize()
        self.enable_v2()

    def enable_v2(self):
        policy = json.loads((ROOT / 'policy.json').read_text())
        policy['compilation_quality_gate'] = True
        self.repo.files[e.POLICY] = e.encoded(policy)

    def add_review(self, title='Story', technical=False, rid=None, editorial=None, **kwargs):
        if rid is None:
            result = self.repo.add(title, **kwargs)
            rid = result['records'][0]['id']
        record = e.lookup(self.repo.state, rid)
        editorial = editorial or review(e.revision(record)['block'], technical)
        self.repo.execute('review_record', record_id=rid, expected_reference=e.reference(record), editorial=editorial)
        return rid

    def test_true_and_omitted_in_both_exports_and_exact_trailer(self):
        self.add_review('Developer API', True)
        self.add_review('ChatGPT consumer app')
        bid = self.repo.prepared(); b = self.repo.state['batches'][bid]
        data = json.loads(self.repo.files[b['json_path']]); txt = self.repo.files[b['txt_path']]
        self.assertIs(data[0]['ds'], True)
        self.assertEqual(list(data[0]), ['title','description','image_url','learn_more_url','date','source','ds'])
        self.assertEqual(list(data[1]), ['title','description','image_url','learn_more_url','date','source'])
        self.assertEqual(txt.count('\nds: true'), 1)
        self.assertEqual(txt, block('Developer API') + '\nds: true\n\n' + block('ChatGPT consumer app') + e.TRAILER)
        self.assertFalse(txt.endswith('\n'))
        self.assertEqual(len(e.revision(self.repo.state['records'][0])['block'].splitlines()), 4)

    def test_all_technical_categories(self):
        for basis in ['api','developer_tool','open_source','research','technical_practice']:
            self.repo.add(basis)
            rid = self.repo.state['next_id']-1
            self.add_review(rid=rid, editorial=review(block(basis), True, basis))
        bid=self.repo.prepared();b=self.repo.state['batches'][bid]
        self.assertTrue(all(x['ds'] is True for x in json.loads(self.repo.files[b['json_path']])))

    def test_no_keyword_classifier_or_silent_default(self):
        self.add_review('ChatGPT API Codex research mentioned in consumer news')
        bid=self.repo.prepared();b=self.repo.state['batches'][bid]
        self.assertNotIn('ds', json.loads(self.repo.files[b['json_path']])[0])
        self.assertNotIn('ds:', self.repo.files[b['txt_path']])

    def test_datasciencecorner_origin_forces_true_without_bot_ds_field(self):
        self.repo.execute('receive',request_id='ds_bot',origin={'kind':'data_science_corner','evidence_sha256':HASH})
        self.repo.execute('finalize',request_id='ds_bot',items=[{'block':block('Paper'),'image_verified':True}])
        with self.assertRaisesRegex(e.LedgerError, 'DataScienceCorner'):
            self.add_review(rid=1, editorial=review(block('Paper')))
        self.add_review(rid=1, editorial=review(block('Paper'),True,'data_science_corner'))
        bid=self.repo.prepared();b=self.repo.state['batches'][bid]
        self.assertIs(json.loads(self.repo.files[b['json_path']])[0]['ds'], True)

    def test_legacy_ds_origin_can_be_evidenced_in_review(self):
        self.repo.add('Legacy bot')
        ed=review(block('Legacy bot'),True,'data_science_corner')
        with self.assertRaisesRegex(e.LedgerError,'provenance'):
            self.add_review(rid=1,editorial=ed)
        ed['origin']={'kind':'data_science_corner','evidence_sha256':HASH}
        self.add_review(rid=1,editorial=ed)
        bid=self.repo.prepared();self.assertIs(json.loads(self.repo.files[self.repo.state['batches'][bid]['json_path']])[0]['ds'],True)

    def test_provenance_follows_own_correction_not_separate_identical_submission(self):
        self.repo.add('Original')
        self.repo.execute('receive',request_id='ds_bot',origin={'kind':'data_science_corner','evidence_sha256':HASH})
        self.repo.execute('finalize',request_id='ds_bot',items=[{'block':block('Original'),'image_verified':True}])
        self.repo.execute('receive',request_id='correction',corrects_record_id=2)
        self.repo.execute('correct',request_id='correction',record_id=2,block=block('Corrected'),image_verified=True)
        with self.assertRaisesRegex(e.LedgerError,'DataScienceCorner'):
            self.add_review(rid=2,editorial=review(block('Corrected')))
        self.add_review(rid=1,editorial=review(block('Original')))
        self.assertEqual(len(self.repo.state['records']),2)

    def test_bool_false_string_ds_and_missing_classification_rejected(self):
        self.repo.add()
        for decision in [True,False,'true',None]:
            ed=review(block());ed['audience']['decision']=decision
            with self.assertRaises(e.LedgerError): self.add_review(rid=1,editorial=ed)
        ed=review(block());ed['ds']=False
        with self.assertRaises(e.LedgerError): self.add_review(rid=1,editorial=ed)

    def test_legacy_intake_does_not_fail_for_missing_review(self):
        self.repo.add('Legacy client')
        self.assertEqual(self.repo.state['requests']['request_1']['status'],'finalized')
        result=self.repo.execute('prepare')
        self.assertEqual(result['status'],'empty')
        self.assertEqual(result['deferred_records'][0]['id'],1)
        self.assertEqual(self.repo.state['checkpoint'],0)
        self.assertEqual(self.repo.state['pending_batch_id'],None)

    def test_ready_subset_compiles_and_unready_record_is_explicitly_deferred(self):
        self.add_review('Ready')
        self.repo.add('Needs research')
        self.add_review('Ready later')
        b=self.repo.execute('prepare')['batch']
        self.assertEqual([r['id'] for r in b['records']],[1,3])
        self.assertEqual([r['id'] for r in b['deferred_records']],[2])
        self.assertEqual(self.repo.state['checkpoint'],0)

    def test_review_reference_cas_and_history_preservation(self):
        self.repo.add('Story'); before=copy.deepcopy(self.repo.state['records'])
        self.add_review(rid=1)
        self.add_review(rid=1,technical=True)
        self.assertEqual(self.repo.state['records'],before)
        self.assertEqual(len(self.repo.state['editorial_reviews']['1:1']),2)
        with self.assertRaisesRegex(e.LedgerError,'target changed'):
            self.repo.execute('review_record',record_id=1,expected_reference={'id':1,'revision':2,'sha256':HASH},editorial=review(block('Story')))

    def test_legacy_pending_retry_bytes_survive_upgrade(self):
        self.repo = Repository().initialize();self.repo.add('Legacy')
        bid=self.repo.prepared(); frozen=copy.deepcopy(self.repo.state['batches'][bid]); files=copy.deepcopy(self.repo.files)
        self.enable_v2(); result=self.repo.execute('prepare')
        self.assertTrue(result['retry']);self.assertEqual(result['batch'],frozen)
        for path in (frozen['txt_path'],frozen['json_path']):self.assertEqual(self.repo.files[path],files[path])
        with self.assertRaisesRegex(e.LedgerError,'frozen'):
            self.add_review(rid=1,technical=True)

    def test_v2_pending_retry_frozen_even_after_quality_age_or_rejection(self):
        self.add_review('Ready',True);bid=self.repo.prepared();b=copy.deepcopy(self.repo.state['batches'][bid])
        self.repo.execute('reject_url',url='https://example.com/image.png',field='image',scope='url',environment='chase',reason='observed_block',evidence_sha256=HASH)
        retry=self.repo.execute('prepare',at='2026-10-05T15:00:00+00:00')
        self.assertEqual(retry['batch'],b)
        self.assertEqual(self.repo.state['checkpoint'],0)

    def test_delivered_history_and_items_never_rewritten(self):
        self.repo=Repository().initialize();self.repo.add('Legacy');bid=self.repo.published();self.repo.begin(bid);self.repo.acknowledge(bid)
        old_files=copy.deepcopy(self.repo.files);old_state=copy.deepcopy(self.repo.state)
        self.enable_v2();self.add_review('New',True);self.repo.prepared()
        for path,value in old_files.items():
            if path.startswith(('items/','workflows/anf/batches/')):self.assertEqual(self.repo.files[path],value)
        self.assertEqual(self.repo.state['batches'][bid],old_state['batches'][bid])
        self.assertEqual(self.repo.state['checkpoint_history'],old_state['checkpoint_history'])
        with self.assertRaisesRegex(e.LedgerError,'delivered'):
            self.add_review(rid=1)

    def test_same_domain_policy_for_article_image_redirects(self):
        for url in ['https://provider.ai/a.png','https://a.provider.ai/a.png','https://OPENAI.COM./a.png','https://cdn.huggingface.co/a.png','https://pbs.twimg.com/a.png']:
            with self.assertRaises(e.LedgerError):
                self.repo.add(url,image=url)
        self.repo.add('Good')
        for field in ['article','image']:
            ed=review(block('Good'));ed['quality'][field]['redirect_chain'].append('https://blocked.ai/final')
            ed['quality'][field]['final_url']='https://blocked.ai/final'
            with self.assertRaisesRegex(e.LedgerError,'policy'):
                self.add_review(rid=1,editorial=ed)

    def test_no_invented_block_for_similar_hostname(self):
        self.repo.add('Allowed',image='https://notopenai.com/image.png')
        self.add_review(rid=1,editorial=review(block('Allowed',image='https://notopenai.com/image.png')))

    def test_quality_rejects_wrong_pixels_small_or_non_image(self):
        self.repo.add('Quality')
        for key,value in [('pixels_inspected',False),('width',599),('height',314),('content_type','text/html'),('relevance','generic_art'),('image_bytes_sha256','')]:
            ed=review(block('Quality'));ed['quality']['image'][key]=value
            with self.assertRaises(e.LedgerError): self.add_review(rid=1,editorial=ed)

    def test_fallback_only_when_story_specific_unavailable(self):
        self.repo.add('Fallback');ed=review(block('Fallback'));ed['quality']['image']['relevance']='official_logo'
        with self.assertRaisesRegex(e.LedgerError,'story-specific'):self.add_review(rid=1,editorial=ed)
        ed['quality']['image'].update(story_specific_available=False,fallback_reason='No usable story-specific image after comparing candidates.')
        self.add_review(rid=1,editorial=ed)

    def test_chase_unknown_is_allowed_verified_needs_evidence(self):
        self.repo.add('Chase');ed=review(block('Chase'))
        self.add_review(rid=1,editorial=ed)
        ed['quality']['image']['chase_status']='verified_accessible'
        with self.assertRaisesRegex(e.LedgerError,'Chase'):self.add_review(rid=1,editorial=ed)
        ed['quality']['image']['chase_evidence_sha256']=HASH
        self.add_review(rid=1,editorial=ed)

    def test_blank_article_allowed_but_blank_image_not(self):
        self.repo.add('No compliant article',url='')
        self.add_review(rid=1,editorial=review(block('No compliant article',url='')))
        with self.assertRaises(e.LedgerError):self.repo.add('No image',image='')

    def test_stale_quality_defers_without_ack_or_fabricated_review(self):
        self.add_review('Old')
        result=self.repo.execute('prepare',at='2026-10-03T15:00:00+00:00')
        self.assertEqual(result['status'],'empty');self.assertIn('stale',result['deferred_records'][0]['reason'])
        self.assertEqual(self.repo.state['checkpoint'],0)

    def test_url_rejections_evidence_scope_and_resolution(self):
        self.repo.add('Rejected');before=self.repo.snapshot()
        with self.assertRaises(e.LedgerError):
            self.repo.execute('reject_url',url='https://example.com/image.png',field='image',scope='host',environment='editorial',reason='irrelevant_image',evidence_sha256=HASH)
        self.assertEqual(self.repo.snapshot(),before)
        r=self.repo.execute('reject_url',url='https://example.com/image.png',field='image',scope='url',environment='editorial',reason='irrelevant_image',evidence_sha256=HASH)
        with self.assertRaisesRegex(e.LedgerError,'evidenced rejection'):self.add_review(rid=1)
        self.repo.execute('resolve_url_rejection',rejection_id=r['rejection_id'],evidence_sha256=HASH)
        self.add_review(rid=1)

    def test_new_review_after_content_correction_required(self):
        self.add_review('Before')
        self.repo.execute('receive',request_id='correction',corrects_record_id=1)
        self.repo.execute('correct',request_id='correction',record_id=1,block=block('After'),image_verified=True)
        self.assertEqual(self.repo.execute('prepare')['status'],'empty')
        self.assertEqual(len(self.repo.state['editorial_reviews']['1:1']),1)

    def test_cas_conflict_replans_without_losing_concurrent_intake(self):
        self.repo.add('Review me');rec=self.repo.state['records'][0]
        op=self.repo.operation('review_record',record_id=1,expected_reference=e.reference(rec),editorial=review(block('Review me')))
        stale=e.plan(self.repo.snapshot(),op)
        self.repo.add('Concurrent')
        with self.assertRaisesRegex(e.LedgerError,'CAS'):self.repo.commit(stale)
        self.repo.commit(e.plan(self.repo.snapshot(),op))
        self.assertEqual(len(self.repo.state['records']),2)
        self.assertEqual(len(self.repo.state['editorial_reviews']['1:1']),1)
        self.assertEqual(e.plan(self.repo.snapshot(),op)['result']['status'],'operation_replayed')


    def test_sparse_delivery_then_gap_catches_up_without_duplicate(self):
        self.add_review('Ready first',True)
        self.repo.add('Needs image work')
        self.add_review('Ready third')
        bid=self.repo.published();self.repo.begin(bid);self.repo.acknowledge(bid)
        self.assertEqual(self.repo.state['checkpoint'],1)
        self.assertEqual(self.repo.execute('status')['queued_count'],1)
        self.assertEqual([r['id'] for r in self.repo.execute('preview')['items']],[2])
        self.repo.add('Late arrival')
        self.add_review(rid=2,technical=True)
        gap=self.repo.published();b=self.repo.state['batches'][gap]
        self.assertEqual([r['id'] for r in b['records']],[2])
        self.assertEqual([r['id'] for r in b['deferred_records']],[4])
        self.repo.begin(gap,attempt='gap');self.repo.acknowledge(gap,attempt='gap')
        self.assertEqual(self.repo.state['checkpoint'],3)
        self.assertEqual([r['id'] for r in self.repo.execute('preview')['items']],[4])
        self.assertEqual(self.repo.state['batches'][gap]['checkpoint_after'],3)
        self.assertEqual(self.repo.state['batches'][bid]['checkpoint_after'],1)
        self.assertEqual(self.repo.add('Ready third')['records'][0]['id'],5)

    def test_unready_first_does_not_hold_later_ready_or_ack_past_gap(self):
        self.repo.add('Unready first');self.add_review('Ready second')
        bid=self.repo.published();self.repo.begin(bid);self.repo.acknowledge(bid)
        self.assertEqual(self.repo.state['checkpoint'],0)
        self.assertEqual(self.repo.execute('prepare')['status'],'empty')
        with self.assertRaisesRegex(e.LedgerError,'frozen'):
            self.add_review(rid=2)
        self.assertEqual(self.repo.execute('status')['queued_count'],1)

    def test_scheduled_pending_correction_defers_only_target(self):
        self.add_review('Correction target');self.add_review('Ready')
        self.repo.execute('receive',request_id='correction',corrects_record_id=1)
        b=self.repo.execute('prepare',eligibility_at=T)['batch']
        self.assertEqual([r['id'] for r in b['records']],[2])
        self.assertEqual([r['id'] for r in b['deferred_records']],[1])
        self.assertIn('correction',b['deferred_request_ids'])

    def test_review_origin_cannot_be_downgraded_later(self):
        self.repo.add('Legacy DS');ed=review(block('Legacy DS'),True,'data_science_corner')
        ed['origin']={'kind':'data_science_corner','evidence_sha256':HASH}
        self.add_review(rid=1,editorial=ed)
        with self.assertRaisesRegex(e.LedgerError,'DataScienceCorner'):
            self.add_review(rid=1,editorial=review(block('Legacy DS')))


    def test_records_20_and_22_ship_then_21_catches_checkpoint_up(self):
        self.repo=Repository().initialize()
        for i in range(1,20):self.repo.add('Historical '+str(i))
        old=self.repo.published();self.repo.begin(old);self.repo.acknowledge(old)
        self.enable_v2()
        self.add_review('Ready 20');self.repo.add('Blocked 21');self.add_review('Ready 22',True)
        bid=self.repo.published();self.assertEqual([r['id'] for r in self.repo.state['batches'][bid]['records']],[20,22])
        self.repo.begin(bid);self.repo.acknowledge(bid)
        self.assertEqual(self.repo.state['checkpoint'],20)
        self.add_review(rid=21)
        gap=self.repo.published();self.assertEqual([r['id'] for r in self.repo.state['batches'][gap]['records']],[21])
        self.repo.begin(gap);self.repo.acknowledge(gap)
        self.assertEqual(self.repo.state['checkpoint'],22)
        self.assertEqual(self.repo.execute('prepare')['status'],'empty')

    def test_sparse_pending_retry_excludes_new_ready_arrivals(self):
        self.repo.add('Gap');self.add_review('Ready')
        bid=self.repo.prepared();frozen=copy.deepcopy(self.repo.state['batches'][bid])
        self.add_review('Later',True)
        self.add_review(rid=1)
        self.assertEqual(self.repo.execute('prepare')['batch'],frozen)
        self.repo.execute('publish',batch_id=bid);self.repo.begin(bid);self.repo.acknowledge(bid)
        next_batch=self.repo.execute('prepare')['batch']
        self.assertEqual([r['id'] for r in next_batch['records']],[1,3])

    def test_gate_reports_sparse_above_checkpoint_record_delivered(self):
        from datetime import datetime
        from test_intake_output_gate import gate
        self.repo.add('Gap')
        self.repo.execute('receive',request_id='sparse')
        op=self.repo.operation('finalize',request_id='sparse',items=[{'block':block('Sparse delivered'),'image_verified':True}])
        self.repo.commit(e.plan(self.repo.snapshot(),op));self.add_review(rid=2)
        bid=self.repo.published();self.repo.begin(bid);self.repo.acknowledge(bid)
        snap=self.repo.snapshot()
        observation={'repository':gate.REPOSITORY,'branch':'main','head':snap['head'],'observed_at':T,'snapshot_sha256':e.digest(e.canonical(snap))}
        result=gate.verify_intake_output(snap,op,observation,now=datetime.fromisoformat(T))
        self.assertEqual(result['items'][0]['queue_status'],'delivered')
        self.assertEqual(len(result['items'][0]['block'].splitlines()),4)

    def test_authorized_url_only_newsletter_intake_records_unknown_verification(self):
        self.repo.execute('receive',request_id='newsletter',mode='image_url_only',image_review_deferral_evidence_sha256=HASH)
        self.repo.execute('finalize',request_id='newsletter',items=[{'block':block('Newsletter'),'image_verified':False}])
        rev=e.revision(self.repo.state['records'][0])
        self.assertEqual(rev['image_verification'],'pending_compilation_review')
        self.assertEqual(self.repo.execute('prepare')['status'],'empty')
        self.add_review(rid=1)
        self.assertEqual(self.repo.execute('prepare')['status'],'prepared')

    def test_url_only_mode_needs_authority_and_still_rejects_bad_url(self):
        with self.assertRaisesRegex(e.LedgerError,'authorization'):
            self.repo.execute('receive',request_id='newsletter',mode='image_url_only')
        self.repo.execute('receive',request_id='newsletter',mode='image_url_only',image_review_deferral_evidence_sha256=HASH)
        for image in ['', 'not a url', 'https://blocked.ai/image.png']:
            with self.assertRaises(e.LedgerError):
                self.repo.execute('finalize',request_id='newsletter',items=[{'block':block('Bad',image=image)}])
        self.assertEqual(self.repo.state['requests']['newsletter']['status'],'received')

    def test_late_rejection_blocks_publish_and_delivery_without_mutating_artifacts(self):
        for published in [False,True]:
            self.setUp();self.add_review('Frozen')
            bid=self.repo.published() if published else self.repo.prepared()
            b=self.repo.state['batches'][bid];frozen={p:self.repo.files[p] for p in [b['txt_path'],b['json_path']]}
            self.repo.execute('reject_url',url='https://example.com/image.png',field='image',scope='url',environment='chase',reason='user_reported_block',evidence_sha256=HASH)
            with self.assertRaisesRegex(e.LedgerError,'active evidenced rejection'):
                self.repo.begin(bid) if published else self.repo.execute('publish',batch_id=bid)
            for p,value in frozen.items():self.assertEqual(self.repo.files[p],value)
            self.assertEqual(self.repo.state['checkpoint'],0)

    def test_late_ds_provenance_blocks_wrong_frozen_classification(self):
        # Compatibility with pre-change ledgers/writers that collapsed duplicates.
        policy=json.loads(self.repo.files[e.POLICY]);policy['preserve_separate_submissions']=False
        self.repo.files[e.POLICY]=e.encoded(policy)
        self.add_review('General at preparation');bid=self.repo.prepared()
        self.repo.execute('receive',request_id='ds_duplicate',origin={'kind':'data_science_corner','evidence_sha256':HASH})
        self.repo.execute('finalize',request_id='ds_duplicate',items=[{'block':block('General at preparation'),'image_verified':True}])
        with self.assertRaisesRegex(e.LedgerError,'Frozen audience conflicts'):
            self.repo.execute('publish',batch_id=bid)
        self.assertNotIn('ds:',self.repo.files[self.repo.state['batches'][bid]['txt_path']])

    def test_separate_identical_submissions_get_distinct_records_and_both_export(self):
        first=self.repo.add('Same article');second=self.repo.add('Same article')
        self.assertEqual([first['records'][0]['id'],second['records'][0]['id']],[1,2])
        self.assertEqual(first['duplicates'],[]);self.assertEqual(second['duplicates'],[])
        self.add_review(rid=1);self.add_review(rid=2)
        bid=self.repo.prepared();b=self.repo.state['batches'][bid]
        self.assertEqual([r['id'] for r in b['records']],[1,2])
        payload=json.loads(self.repo.files[b['json_path']]);self.assertEqual(len(payload),2);self.assertEqual(payload[0],payload[1])
        self.assertEqual(self.repo.files[b['txt_path']].count('Title: Same article'),2)

    def test_same_request_and_operation_retries_allocate_no_new_record(self):
        self.repo.execute('receive',request_id='same')
        op=self.repo.operation('finalize',request_id='same',items=[{'block':block('Same'),'image_verified':True}])
        self.repo.commit(e.plan(self.repo.snapshot(),op))
        replay=e.plan(self.repo.snapshot(),op);self.assertTrue(replay['replayed']);self.assertEqual(replay['changes'],[])
        self.repo.execute('receive',request_id='same')
        with self.assertRaisesRegex(e.LedgerError,'already resolved'):
            self.repo.execute('finalize',request_id='same',items=[{'block':block('Same'),'image_verified':True}])
        self.assertEqual(len(self.repo.state['records']),1)

    def test_identical_items_in_one_accepted_submission_preserve_expected_count(self):
        self.repo.execute('receive',request_id='two',expected_items=2)
        result=self.repo.execute('finalize',request_id='two',items=[{'block':block('Same'),'image_verified':True}]*2)
        self.assertEqual([r['id'] for r in result['records']],[1,2]);self.assertEqual(result['duplicates'],[])

    def test_separate_submission_of_delivered_content_is_new_without_rewriting_history(self):
        self.add_review('Repeat',True);bid=self.repo.published();self.repo.begin(bid);self.repo.acknowledge(bid)
        before=copy.deepcopy(self.repo.state['batches'][bid]);files={p:v for p,v in self.repo.files.items() if p.startswith(('items/','workflows/anf/batches/'))}
        self.assertEqual(self.repo.add('Repeat')['records'][0]['id'],2)
        self.assertEqual(self.repo.state['checkpoint'],1);self.assertEqual(self.repo.state['batches'][bid],before)
        for p,v in files.items():self.assertEqual(self.repo.files[p],v)
        self.assertEqual([r['id'] for r in self.repo.execute('preview')['items']],[2])

    def test_explicit_correction_can_match_other_record_without_collapsing(self):
        self.repo.add('First');self.repo.add('Second')
        self.repo.execute('receive',request_id='explicit_correction',corrects_record_id=2)
        result=self.repo.execute('correct',request_id='explicit_correction',record_id=2,block=block('First'),image_verified=True)
        self.assertEqual(result['record']['id'],2);self.assertEqual(result['record']['revision'],2)
        self.assertEqual(len(self.repo.state['records']),2)
        self.assertEqual(e.revision(self.repo.state['records'][0])['block'],e.revision(self.repo.state['records'][1])['block'])

    def test_automatic_reconciliation_cannot_suppress_a_separate_submission(self):
        self.repo.add('Existing');self.repo.execute('receive',request_id='new')
        before=self.repo.snapshot()
        with self.assertRaisesRegex(e.LedgerError,'automatically reconciled'):
            self.repo.execute('reconcile_intake',request_id='new',record_ids=[1],evidence_sha256=HASH)
        self.assertEqual(self.repo.snapshot(),before)
        self.repo.execute('reconcile_intake',request_id='new',record_ids=[1],evidence_sha256=HASH,
                          reconciliation_reason='user_authorized_mapping',authorization_sha256=HASH)
        self.assertEqual(self.repo.state['requests']['new']['status'],'reconciled')

    def test_delivery_retry_remains_exact_once_with_separate_same_story_queued(self):
        self.add_review('Same');bid=self.repo.published();self.repo.begin(bid)
        self.repo.execute('delivery_failed',batch_id=bid,attempt_id='attempt_1',definitely_not_accepted=True,evidence_sha256=HASH)
        self.repo.add('Same');pub=self.repo.state['batches'][bid]['publication']
        self.assertEqual(self.repo.execute('prepare')['batch']['records'][0]['id'],1)
        self.assertEqual(self.repo.execute('publish',batch_id=bid)['publication'],pub)
        self.repo.begin(bid,attempt='retry');self.repo.acknowledge(bid,attempt='retry')
        self.assertEqual(self.repo.state['checkpoint'],1)
        self.assertEqual([r['id'] for r in self.repo.execute('preview')['items']],[2])

    def test_output_gate_releases_new_identical_submission_as_new_record(self):
        from datetime import datetime
        from test_intake_output_gate import gate
        self.repo.add('Identical')
        self.repo.execute('receive',request_id='new_identical')
        op=self.repo.operation('finalize',request_id='new_identical',items=[{'block':block('Identical'),'image_verified':True}])
        self.repo.commit(e.plan(self.repo.snapshot(),op));snap=self.repo.snapshot()
        observation={'repository':gate.REPOSITORY,'branch':'main','head':snap['head'],'observed_at':T,'snapshot_sha256':e.digest(e.canonical(snap))}
        result=gate.verify_intake_output(snap,op,observation,now=datetime.fromisoformat(T))
        self.assertEqual(result['items'][0]['id'],2);self.assertEqual(result['items'][0]['queue_status'],'queued')
        self.assertEqual(result['items'][0]['block'],block('Identical'))

if __name__ == '__main__': unittest.main()
