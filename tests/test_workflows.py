"""Command-level regressions using synthetic mail and real local state handling."""
import io
import json
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from typer.testing import CliRunner

from msmail.cli import app
from msmail.core import auth, compose, graph, mail

runner = CliRunner()


@pytest.fixture
def mailbox(monkeypatch):
    account = 'me@example.invalid'
    auth._set_active(account)
    acquisitions = []
    requests = []

    def acquire(scopes, account):
        acquisitions.append(account)
        return {'access_token': 'synthetic-token', 'expires_in': 3600}

    monkeypatch.setattr(auth, '_app', lambda cache: SimpleNamespace(
        get_accounts=lambda: [{'username': account}], acquire_token_silent=acquire,
    ))

    def urlopen(request, timeout=None):
        path = urlsplit(request.full_url).path
        method = request.get_method()
        requests.append((method, path))
        message_id = path.split('/')[-2 if path.endswith('/move') else -1]
        message = {
            'id': message_id, 'subject': 'Synthetic message', 'isDraft': True,
            'from': {'emailAddress': {'address': 'sender@example.invalid'}},
            'body': {'contentType': 'Text', 'content': 'Synthetic body'},
        }
        return io.BytesIO(json.dumps(message).encode() if method in ('GET', 'POST') else b'')

    monkeypatch.setattr(graph.request, 'urlopen', urlopen)
    return SimpleNamespace(account=account, acquisitions=acquisitions, requests=requests)


@pytest.mark.parametrize('command,options,method', [
    ('delete', ['--yes'], 'DELETE'),
    ('move', ['--folder', 'deleted', '--yes'], 'POST'),
    ('mark', ['--read'], 'PATCH'),
])
def test_mutation_survives_broken_list_cache(mailbox, caplog, command, options, method):
    auth.account_dir(mailbox.account).joinpath('last-list.json').write_text('{broken')
    result = runner.invoke(app, [command, '--id', 'messageID', '--json', *options])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)['id'] == 'messageID'
    assert sum(verb == method for verb, _ in mailbox.requests) == 1
    assert 'operation succeeded' in caplog.text
    assert 'msmail list' in caplog.text


@pytest.mark.parametrize('command,options', [
    ('delete', ['--yes']), ('move', ['--folder', 'deleted', '--yes']),
])
def test_preview_is_reused_and_token_acquired_once_per_command(mailbox, command, options):
    for _ in range(2):
        result = runner.invoke(app, [command, '--id', 'messageID', '--json', *options])
        assert result.exit_code == 0, result.output
    assert len(mailbox.acquisitions) == 2  # One per invocation, never retained across commands.
    assert sum(method == 'GET' for method, _ in mailbox.requests) == 2


@pytest.mark.parametrize('command,options,operation', [
    ('delete', ['--yes', '--json'], 'delete_empty'),
    ('move', ['--yes', '--json', '--folder', 'deleted'], 'post_json'),
    ('mark', ['--read', '--json'], 'patch_json'),
    ('draft', ['send', '--yes'], 'post_empty'),
])
def test_batch_failure_reports_completed_ids_and_stops(mailbox, monkeypatch, command, options, operation):
    auth.account_dir(mailbox.account).joinpath('last-list.json').write_text(json.dumps({
        'messages': [{'index': i, 'id': f'message{i}'} for i in range(1, 4)],
    }))
    attempted = []

    def mutate(path, token, **kwargs):
        attempted.append(path)
        if len(attempted) == 2:
            raise graph.GraphError('synthetic failure')
        return {'id': 'message1'}

    monkeypatch.setattr(graph, operation, mutate)
    args = [command, '1-3', *options] if command != 'draft' else ['draft', 'send', '1-3', '--yes']
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert len(attempted) == 2
    assert 'Completed IDs: message1' in result.output
    assert 'failed for message2' in result.output
    assert 'Remaining items were not attempted' in result.output


@pytest.mark.parametrize('args,expected', [
    (['list'], 'No active account'),
    (['list', '--folder', 'unknown'], 'Unknown folder'),
    (['draft', 'create', '--file', '/nonexistent-msmail-review-file'], 'No such file'),
    (['reply', '--id', 'messageID', '--body-file', '/nonexistent-msmail-review-file'], 'No such file'),
])
def test_expected_errors_are_printed_without_tracebacks(args, expected):
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert expected in result.output
    assert 'Traceback' not in result.output


def test_programming_errors_are_not_relabelled_as_user_errors(monkeypatch):
    def broken(**kwargs):
        raise RuntimeError('programming defect')
    monkeypatch.setattr(mail, 'list_messages', broken)
    result = runner.invoke(app, ['list'])
    assert isinstance(result.exception, RuntimeError)
    assert result.output == ''


@pytest.mark.parametrize('command', [['send'], ['draft', 'create']])
@pytest.mark.parametrize('conflict', [['--subject', 'ignored'], ['--body', ''], ['--attach', 'ignored']])
def test_compose_file_rejects_conflicting_inputs(tmp_path, command, conflict):
    path = tmp_path / 'compose.txt'
    path.write_text(compose.compose_template(to='to@example.invalid', subject='Test', body='Body'))
    result = runner.invoke(app, [*command, '--file', str(path), *conflict])
    assert result.exit_code == 1
    assert '--file cannot be combined' in result.output


@pytest.mark.parametrize('command', [['send'], ['draft', 'create']])
def test_empty_body_option_still_conflicts_with_body_file(tmp_path, command):
    path = tmp_path / 'body.txt'
    path.write_text('Body')
    result = runner.invoke(app, [*command, '--to', 'to@example.invalid', '--subject', 'Test',
                                 '--body', '', '--body-file', str(path)])
    assert result.exit_code == 1
    assert 'Use only one of --body or --body-file' in result.output


def test_send_without_inputs_never_opens_an_editor(monkeypatch):
    monkeypatch.setattr(compose, 'compose_interactively', lambda *a, **k: pytest.fail('editor opened'))
    result = runner.invoke(app, ['send'])
    assert result.exit_code == 1
    assert 'never opens an editor' in result.output


def test_cache_write_failure_after_delete_is_only_a_warning(mailbox, monkeypatch, caplog):
    auth.account_dir(mailbox.account).joinpath('last-list.json').write_text(json.dumps({
        'messages': [{'index': 1, 'id': 'messageID'}],
    }))
    def failed_write(*args):
        raise OSError('disk full')
    monkeypatch.setattr(auth, 'write_private_text', failed_write)
    result = runner.invoke(app, ['delete', '--id', 'messageID', '--yes', '--json'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)['id'] == 'messageID'
    assert 'disk full' in caplog.text
