"""Offline synthetic connector observations; no GitHub or scheduler actions."""
import base64
import copy
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('connector_snapshot', ROOT / 'connector_snapshot.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
HEAD = 'a' * 40


def object_sha(kind, raw):
    return hashlib.sha1((kind + ' ' + str(len(raw))).encode() + b'\0' + raw).hexdigest()


def fixture(files=None, modes=None):
    files = files or {'workflows/anf/ledger.json': '{"records": []}\n',
                      'workflows/anf/policy.json': '{}\n',
                      'workflows/anf/runtime_config.json': '{}',
                      'items/2026-11-04.json': '[]\n',
                      'README.md': 'Unrelated content\n'}
    modes = modes or {}
    entries, blobs, directories = {}, {}, {''}
    for path, content in files.items():
        raw = content if isinstance(content, bytes) else content.encode('utf-8')
        blob_sha = object_sha('blob', raw)
        entries[path] = {'path': path, 'sha': blob_sha, 'type': 'blob',
                         'mode': modes.get(path, '100644'), 'size': len(raw)}
        if c.required_path(path):
            blobs[blob_sha] = {'sha': blob_sha, 'size': len(raw), 'encoding': 'base64',
                               'content': base64.b64encode(raw).decode('ascii')}
        parent = path.rpartition('/')[0]
        while parent:
            directories.add(parent)
            parent = parent.rpartition('/')[0]
    root_sha = None
    for directory in sorted(directories, key=lambda p: (p.count('/'), len(p)), reverse=True):
        children = [entry for path, entry in entries.items() if path.rpartition('/')[0] == directory]
        children.sort(key=lambda entry: entry['path'].rsplit('/', 1)[-1].encode()
                      + (b'/' if entry['type'] == 'tree' else b''))
        raw = b''
        for entry in children:
            raw += (entry['mode'].lstrip('0') + ' ').encode()
            raw += entry['path'].rsplit('/', 1)[-1].encode() + b'\0' + bytes.fromhex(entry['sha'])
        digest = object_sha('tree', raw)
        if directory:
            entries[directory] = {'path': directory, 'sha': digest, 'type': 'tree', 'mode': '040000'}
        else:
            root_sha = digest
    return {'head': HEAD, 'observed_head': HEAD,
            'commit': {'sha': HEAD, 'tree': {'sha': root_sha}},
            'tree': {'sha': root_sha, 'truncated': False, 'tree': list(entries.values())},
            'blobs': list(blobs.values())}


class ConnectorSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.observation = fixture()

    def rejected(self, observation=None, message=None):
        with self.assertRaisesRegex(c.SnapshotError, message or '.'):
            c.assemble_snapshot(self.observation if observation is None else observation)

    def test_exact_scope_and_no_observation_mutation(self):
        before = copy.deepcopy(self.observation)
        snapshot = c.assemble_snapshot(self.observation)
        self.assertEqual(snapshot, {'head': HEAD, 'complete': True, 'files': {
            'workflows/anf/ledger.json': '{"records": []}\n', 'workflows/anf/policy.json': '{}\n',
            'workflows/anf/runtime_config.json': '{}', 'items/2026-11-04.json': '[]\n'}})
        self.assertEqual(self.observation, before)

    def test_rest_commit_response_and_plain_utf8_blobs(self):
        self.observation['commit'] = {'sha': HEAD, 'commit': {'tree': self.observation['commit']['tree']}}
        for blob in self.observation['blobs']:
            blob.update(encoding='utf-8', content=base64.b64decode(blob['content']).decode())
        self.assertTrue(c.assemble_snapshot(self.observation)['complete'])

    def test_large_utf8_ledger_exact_bytes_and_line_endings(self):
        content = '{"text":"' + 'á界🙂' * 300000 + '\\r\\n"}\r\n'
        observation = fixture({'workflows/anf/ledger.json': content,
            'workflows/anf/policy.json': '{}\n', 'workflows/anf/runtime_config.json': '{}'})
        result = c.assemble_snapshot(observation)
        self.assertGreater(len(content.encode()), 2 * 1024 * 1024)
        self.assertEqual(result['files']['workflows/anf/ledger.json'].encode(), content.encode())

    def test_shared_blob_and_empty_file_are_valid(self):
        observation = fixture({'workflows/anf/ledger.json': '{}', 'workflows/anf/policy.json': '{}',
                               'workflows/anf/runtime_config.json': '{}', 'workflows/anf/empty.txt': ''})
        self.assertEqual(len(observation['blobs']), 2)
        self.assertEqual(c.assemble_snapshot(observation)['files']['workflows/anf/empty.txt'], '')

    def test_git_tree_sorting_and_unrelated_binary(self):
        observation = fixture({'workflows/anf/ledger.json': '{}', 'workflows/anf/policy.json': '{}',
            'workflows/anf/runtime_config.json': '{}', 'items/nested/file.json': '[]',
            'foo.bar': b'\xff', 'foo/baz': b'\xfe', 'föö/file': 'ö'})
        self.assertEqual(len(c.assemble_snapshot(observation)['files']), 4)

    def test_changed_head_and_mismatched_commit_fail(self):
        for key in ('head', 'observed_head'):
            bad = copy.deepcopy(self.observation); bad[key] = 'b' * 40
            self.rejected(bad, 'HEAD changed')
        self.observation['commit']['sha'] = 'b' * 40
        self.rejected(message='commit identity')

    def test_tree_must_be_fetched_by_root_tree_not_commit(self):
        self.observation['tree']['sha'] = HEAD
        self.rejected(message='Tree identity')

    def test_truncated_or_absent_completeness_flag_fails(self):
        for value in (True, None, 0, 'false'):
            bad = copy.deepcopy(self.observation); bad['tree']['truncated'] = value
            self.rejected(bad, 'Incomplete recursive')

    def test_missing_entry_detected_even_when_not_truncated(self):
        # An omitted unrelated file still invalidates the root tree commitment.
        self.observation['tree']['tree'] = [entry for entry in self.observation['tree']['tree']
                                           if entry['path'] != 'README.md']
        self.rejected(message='Incomplete or altered')

    def test_missing_parent_directory_fails(self):
        self.observation['tree']['tree'] = [entry for entry in self.observation['tree']['tree']
                                           if entry['path'] != 'workflows']
        self.rejected(message='Missing directory')

    def test_duplicate_tree_path_fails(self):
        self.observation['tree']['tree'].append(copy.deepcopy(self.observation['tree']['tree'][0]))
        self.rejected(message='Duplicate tree path')

    def test_missing_mandatory_path_fails(self):
        self.rejected(fixture({'workflows/anf/policy.json': '{}'}), 'Mandatory snapshot')

    def test_missing_duplicate_and_extra_blobs_fail(self):
        bad = copy.deepcopy(self.observation); bad['blobs'].pop(); self.rejected(bad, 'blobs missing')
        bad = copy.deepcopy(self.observation); bad['blobs'].append(bad['blobs'][0]); self.rejected(bad, 'Duplicate fetched')
        bad = copy.deepcopy(self.observation); extra = {**bad['blobs'][0], 'sha': 'b' * 40}
        bad['blobs'].append(extra); self.rejected(bad, 'Unexpected fetched')

    def test_empty_contents_response_and_truncated_blob_fail(self):
        for content in ('', self.observation['blobs'][0]['content'][:4]):
            bad = copy.deepcopy(self.observation); bad['blobs'][0]['content'] = content
            self.rejected(bad, 'Empty, truncated or altered')
        bad = copy.deepcopy(self.observation); bad['blobs'][0].update(content='', encoding='none')
        self.rejected(bad, 'use fetch_blob')

    def test_wrong_content_hash_even_with_matching_size_fails(self):
        bad = self.observation['blobs'][0]
        bad['content'] = base64.b64encode(b'x' * bad['size']).decode()
        self.rejected(message='altered fetched blob')

    def test_blob_and_tree_byte_sizes_are_checked(self):
        for field in ('blob', 'tree'):
            bad = copy.deepcopy(self.observation)
            item = bad['blobs'][0] if field == 'blob' else next(
                entry for entry in bad['tree']['tree'] if entry['path'] == 'workflows/anf/ledger.json')
            item['size'] += 1
            self.rejected(bad, 'altered fetched blob|size differs')

    def test_byte_size_not_character_count(self):
        observation = fixture({'workflows/anf/ledger.json': 'é', 'workflows/anf/policy.json': '{}',
                               'workflows/anf/runtime_config.json': '{}'})
        observation['blobs'][0]['size'] = 1
        self.rejected(observation, 'altered fetched blob')

    def test_invalid_base64_and_non_utf8_fail(self):
        self.observation['blobs'][0]['content'] = '!!!'
        self.rejected(message='base64')
        self.rejected(fixture({'workflows/anf/ledger.json': b'\xff', 'workflows/anf/policy.json': '{}',
            'workflows/anf/runtime_config.json': '{}'}), 'not UTF-8')

    def test_base64_line_wrapping_is_supported(self):
        for blob in self.observation['blobs']:
            blob['content'] = '\r\n'.join(blob['content'][i:i+4] for i in range(0, len(blob['content']), 4))
        self.assertTrue(c.assemble_snapshot(self.observation)['complete'])

    def test_authoritative_symlink_rejected(self):
        self.rejected(fixture(modes={'workflows/anf/ledger.json': '120000'}), 'Unsupported file type')

    def test_invalid_paths_and_modes_fail(self):
        for path in ('../ledger.json', '/workflows/anf/ledger.json', 'workflows//anf/a', 'workflows/./a',
                     'workflows/anf/a\0b', 'workflows\\anf\\a'):
            bad = copy.deepcopy(self.observation); bad['tree']['tree'][0]['path'] = path
            self.rejected(bad, 'Invalid tree path')
        self.observation['tree']['tree'][0]['mode'] = '040000'
        self.rejected(message='mode/type')

    def test_invalid_sha_and_size_types_fail(self):
        for value in ('0' * 40, 'a' * 64, 'A' * 40, None):
            bad = copy.deepcopy(self.observation); bad['head'] = value; self.rejected(bad, 'SHA-1')
        for value in (True, -1, '14', None):
            bad = copy.deepcopy(self.observation); bad['blobs'][0]['size'] = value
            self.rejected(bad, 'byte size')

    def test_duplicate_json_keys_and_nonfinite_numbers_fail(self):
        for text in ('{"head":1,"head":2}', '{"value":NaN}'):
            with self.assertRaises(c.SnapshotError): c.strict_json(text)

    def test_cli_failure_replaces_prior_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = pathlib.Path(directory) / 'input.json', pathlib.Path(directory) / 'output.json'
            source.write_text(json.dumps(self.observation))
            command = [sys.executable, str(ROOT / 'connector_snapshot.py'), '--input', str(source), '--output', str(output)]
            first = subprocess.run(command, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue(json.loads(output.read_text())['complete'])
            self.observation['observed_head'] = 'b' * 40
            source.write_text(json.dumps(self.observation))
            second = subprocess.run(command, capture_output=True)
            self.assertEqual(second.returncode, 1, second.stderr)
            self.assertEqual(json.loads(output.read_text())['status'], 'snapshot_blocked')
            self.assertNotIn('files', json.loads(output.read_text()))


if __name__ == '__main__':
    unittest.main()
