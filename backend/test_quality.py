"""Regression tests for data integrity, security and cross-window workflows."""
import copy
import io
import json
import sqlite3
import threading
from unittest.mock import patch
from uuid import uuid4
from contextlib import redirect_stdout
import manage_store

import server
from classification import normalize
from test_ab import ServiceCase, prediction


class QualityContracts(ServiceCase):
    def raw(self, method='POST', path='/api/reset', headers=None, raw=b'{}'):
        environ = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'HTTP_HOST': '127.0.0.1:8780',
                   'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(raw)),
                   'HTTP_X_CSRF_TOKEN': server.CSRF_TOKEN, 'wsgi.input': io.BytesIO(raw)}
        environ.update(headers or {})
        response = {}
        def start(status, fields):
            response.update(status=int(status.split()[0]), headers=dict(fields))
        response['body'] = json.loads(b''.join(server.application(environ, start)))
        return response

    def test_cross_site_get_and_host_spoof_cannot_read_session_or_tickets(self):
        for headers in ({'HTTP_HOST': 'attacker.example'}, {'HTTP_HOST': 'user@localhost:8780'},
                        {'HTTP_ORIGIN': 'null'}, {'HTTP_ORIGIN': 'https://untrusted.example'},
                        {'HTTP_SEC_FETCH_SITE': 'cross-site'}, {'HTTP_HOST': '[invalid'}):
            with self.subTest(headers=headers):
                response = self.raw('GET', '/api/session', headers)
                self.assertEqual(response['status'], 403)
                self.assertNotIn('csrf_token', response['body'])

    def test_mutations_require_valid_csrf_token(self):
        before = copy.deepcopy(server.tickets)
        for token in ('', 'wrong'):
            self.assertEqual(self.raw(headers={'HTTP_X_CSRF_TOKEN': token})['status'], 403)
        self.assertEqual(before, server.tickets)

    def test_security_headers_are_also_on_errors(self):
        response = self.raw('GET', '/api/unknown')
        self.assertEqual(response['status'], 404)
        self.assertEqual(response['headers']['Cache-Control'], 'no-store')
        self.assertEqual(response['headers']['X-Content-Type-Options'], 'nosniff')
        self.assertIn('X-Request-ID', response['headers'])
        self.assertNotIn('Traceback', str(response['body']))

    def test_invalid_payloads_and_unknown_methods_never_invoke_model(self):
        for raw in (b'[]', b'null', b'broken', b'{"provider":[]}', b'{"provider":"jev","id":[]}'):
            self.assertEqual(self.raw(path='/api/analyze', raw=raw)['status'], 400)
        self.assertEqual(self.raw(raw=b' ' * (server.MAX_BODY + 1))['status'], 413)
        self.assertEqual(self.raw(headers={'CONTENT_TYPE': 'text/plain'})['status'], 415)
        self.assertEqual(self.raw('DELETE')['status'], 405)
        self.local_mock.assert_not_called()
        self.remote_mock.assert_not_called()

    def test_disk_failure_does_not_mutate_memory_or_report_success(self):
        server.save()
        before = copy.deepcopy(server.tickets)
        with patch.object(server.TicketStore, 'save', side_effect=OSError('disk full')):
            response = self.raw(path='/api/tickets', raw=json.dumps({'subject': 'test', 'message': 'test'}).encode())
        self.assertEqual(response['status'], 503)
        self.assertEqual(server.tickets, before)
        self.assertEqual(server.TicketStore(server.DATA).load(), before)

    def test_analysis_commit_failure_preserves_previous_result_and_unlocks(self):
        self.call('analyze', {'id': 'TK-1042'})
        before = copy.deepcopy(server.tickets)
        with patch.object(server.TicketStore, 'save', side_effect=sqlite3.OperationalError('read only')):
            self.call('analyze', {'id': 'TK-1042'}, 503)
        self.assertEqual(server.tickets, before)
        self.assertFalse(server.inference_locks['laya-ft'].locked())

    def test_create_retry_is_idempotent_and_conflicting_content_rejected(self):
        body = {'subject': 'Repeated request', 'message': 'Fictional feedback', 'request_id': str(uuid4())}
        first = self.call('tickets', body, 201)['ticket']
        second = self.call('tickets', body)['ticket']
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(server.tickets), 9)
        self.call('tickets', {**body, 'message': 'Different content'}, 409)

    def test_stale_tab_cannot_assign_newer_analysis(self):
        old = self.call('analyze', {'id': 'TK-1042'})['ticket']
        self.call('analyze', {'id': 'TK-1042'})
        self.call('assign', {'id': 'TK-1042', 'team': '售前顾问', 'expected_revision': old['revision']}, 409)
        self.assertIsNone(server.tickets[6]['runs']['laya-ft']['team'])

    def test_assignment_retries_do_not_duplicate_history_and_reopen_isolated(self):
        self.call('analyze', {'id': 'TK-1042'})
        first = self.call('assign', {'id': 'TK-1042', 'team': '售前顾问'})['ticket']
        repeated = self.call('assign', {'id': 'TK-1042', 'team': '售前顾问'})['ticket']
        self.assertEqual(first['history'], repeated['history'])
        opened = self.call('reopen', {'id': 'TK-1042', 'expected_revision': first['revision']})['ticket']
        self.assertEqual(opened['status'], 'analyzed')
        self.assertIsNone(opened['team'])
        self.assertEqual(opened['runs']['jev'], first['runs']['jev'])
        self.call('analyze', {'id': 'TK-1042'})

    def test_changed_checkpoint_is_rejected_even_if_client_skips_validation(self):
        t = server.tickets[6]
        t['runs']['laya-ft'].update(status='analyzed', analysis=normalize(prediction(), 'laya-ft', 10,
            {'subject': t['subject'], 'message': t['message']}, '00:00'))
        with patch.object(server, 'statuses', return_value={'laya-ft': {'status': 'ready', 'model': 'new-checkpoint'}}):
            self.call('assign', {'id': t['id'], 'provider': 'laya-ft', 'team': '售前顾问'}, 409)

    def test_parallel_models_keep_both_results_and_assignment_is_blocked_during_inference(self):
        entered, release = threading.Event(), threading.Event()
        def slow(state, questions):
            entered.set()
            self.assertTrue(release.wait(4))
            return prediction('sales')
        self.local_mock.side_effect = slow
        results = []
        worker = threading.Thread(target=lambda: results.append(self.call('analyze', {'id': 'TK-1042'})))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.call('analyze', {'id': 'TK-1042'}, 409)
            self.call('assign', {'id': 'TK-1042', 'team': '售前顾问'}, 409)
            self.call('analyze', {'id': 'TK-1042', 'provider': 'jev'})
        finally:
            release.set()
            worker.join(4)
        self.assertEqual(len(results), 1)
        stored = server.TicketStore(server.DATA).load()[6]['runs']
        self.assertEqual(stored['laya-ft']['analysis']['category'], 'sales')
        self.assertEqual(stored['jev']['analysis']['category'], 'account')

    def test_reset_preserves_database_backup_and_failure_does_not_reset_generation(self):
        self.call('analyze', {'id': 'TK-1042'})
        before = copy.deepcopy(server.tickets)
        with patch.object(server.TicketStore, 'save', side_effect=OSError('disk full')):
            self.call('reset', {}, 503)
        self.assertEqual(server.tickets, before)
        self.assertEqual(server.generation, 0)
        self.call('reset', {})
        backup = server.TicketStore(server.DATA.with_name('data.before-reset.json')).load()
        self.assertEqual(backup, before)
        self.assertIsNone(server.tickets[6]['runs']['laya-ft']['analysis'])

    def test_rate_limit_is_bounded_and_does_not_block_reads(self):
        with server.limiter.lock:
            server.limiter.times.extend([server.time.monotonic()] * 120)
        response = self.raw()
        self.assertEqual(response['status'], 429)
        self.assertEqual(response['headers']['Retry-After'], '60')
        self.assertEqual(self.raw('GET', '/api/tickets')['status'], 200)

    def test_backup_restore_roundtrip_uses_validated_state(self):
        server.save()
        before = copy.deepcopy(server.tickets)
        backup = server.TicketStore(server.DATA).backup('manual')
        server.tickets[0]['subject'] = 'Changed after backup'
        server.save()
        with patch.object(manage_store, 'DATA', server.DATA), patch('sys.argv', ['manage_store', 'restore', str(backup)]), \
                patch.object(manage_store.socket, 'create_connection', side_effect=OSError()), redirect_stdout(io.StringIO()):
            manage_store.main()
        self.assertEqual(server.TicketStore(server.DATA).load(), before)
        prior = server.TicketStore(server.DATA.with_name('data.before-restore.json')).load()
        self.assertEqual(prior[0]['subject'], 'Changed after backup')

    def test_invalid_backup_is_rejected_without_changing_current_database(self):
        server.save()
        before = server.TicketStore(server.DATA).load()
        invalid = server.DATA.with_name('invalid.sqlite3')
        invalid.write_bytes(b'not a sqlite database')
        with patch.object(manage_store, 'DATA', server.DATA), patch('sys.argv', ['manage_store', 'restore', str(invalid)]), \
                patch.object(manage_store.socket, 'create_connection', side_effect=OSError()):
            with self.assertRaises(sqlite3.DatabaseError):
                manage_store.main()
        self.assertEqual(server.TicketStore(server.DATA).load(), before)
