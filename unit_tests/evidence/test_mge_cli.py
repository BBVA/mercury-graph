import os, runpy, sys

from unittest.mock import Mock

import pytest

import cli.mge as mge


def _args(command = 'complete', name = 'endpoint', **kwargs):
	args = {'command': command, 'name': name, 'intent': None, 'just_once': False,
			'log_file': None, 'port': None}
	args.update(kwargs)
	return args


def _endpoint(state = 100, state_name = 'READY', lock = None):
	endpoint = Mock()
	endpoint.id = 'endpoint-id'
	endpoint.meta = {'state': state}
	endpoint.state_name.return_value = state_name
	endpoint.lock.return_value = mge.mg.evidence.endpoint.LockState.LOCK if lock is None else lock
	return endpoint


def test_file_logger_and_http_server(monkeypatch, tmp_path):
	log_file = tmp_path / 'events.log'
	logger = mge.MgeFileLogger(str(log_file))
	logger.append({'event': 'created'})
	assert log_file.read_text() == "{'event': 'created'}\n"

	endpoint = Mock()
	endpoint.meta = {'state': 1}
	endpoint.run.return_value = {'result': 'run'}
	endpoint.dry_run.return_value = {'result': 'dry'}
	server = mge.MgeHttpServe(endpoint)
	assert server.meta() == {'state': 1}
	assert server.run({'request': 1}) == {'result': 'run'}
	assert server.dry_run({'request': 1}) == {'result': 'dry'}

	with pytest.raises(mge.HTTPException, match = 'Request body'):
		server.run([])
	with pytest.raises(mge.HTTPException, match = 'Request body'):
		server.dry_run([])

	for exception, status, detail in [
		(mge.mg.evidence.agentic.AgenticRunInvalidRequest(), 400, 'Invalid request.'),
		(mge.mg.evidence.agentic.AgenticRunInvalidState(), 503, 'Invalid state.'),
		(mge.mg.evidence.agentic.AgenticRunFailed(), 500, 'Run failed.')]:
		endpoint.run.side_effect = exception
		with pytest.raises(mge.HTTPException) as error:
			server.run({})
		assert (error.value.status_code, error.value.detail) == (status, detail)

	endpoint.run.side_effect = mge.HTTPException(status_code = 418, detail = 'teapot')
	with pytest.raises(mge.HTTPException) as error:
		server.run({})
	assert error.value.status_code == 418
	endpoint.run.side_effect = RuntimeError('broken')
	with pytest.raises(mge.HTTPException) as error:
		server.run({})
	assert (error.value.status_code, error.value.detail) == (500, 'broken')

	endpoint.dry_run.side_effect = mge.HTTPException(status_code = 418, detail = 'teapot')
	with pytest.raises(mge.HTTPException) as error:
		server.dry_run({})
	assert error.value.status_code == 418
	endpoint.dry_run.side_effect = RuntimeError('broken')
	with pytest.raises(mge.HTTPException) as error:
		server.dry_run({})
	assert (error.value.status_code, error.value.detail) == (500, 'broken')
	class ErrorEndpoint:
		def __init__(self, error):
			self.error = error

		@property
		def meta(self):
			raise self.error

	server.ep = ErrorEndpoint(mge.HTTPException(status_code = 418, detail = 'teapot'))
	with pytest.raises(mge.HTTPException) as error:
		server.meta()
	assert error.value.status_code == 418
	server.ep = ErrorEndpoint(RuntimeError('broken'))
	with pytest.raises(mge.HTTPException) as error:
		server.meta()
	assert (error.value.status_code, error.value.detail) == (500, 'broken')

	uvicorn_run = Mock()
	monkeypatch.setattr(mge.uvicorn, 'run', uvicorn_run)
	server.serve(8000)
	uvicorn_run.assert_called_once_with(server.app, host = '0.0.0.0', port = 8000)


def test_cli_init_and_exec_errors(monkeypatch, capsys):
	for args, message in [
		(_args('pilot'), 'intent argument is required'),
		(_args('serve', intent = 'READY'), 'port argument is required'),
		(_args('serve', intent = 'READY', port = 'bad'), 'port argument must be an integer')]:
		with pytest.raises(SystemExit):
			mge.MgeCli(args)
		assert message in capsys.readouterr().out

	monkeypatch.setattr(mge, 'MgeFileLogger', Mock(side_effect = OSError()))
	with pytest.raises(SystemExit):
		mge.MgeCli(_args('pilot', intent = 'READY', log_file = 'bad.log'))
	assert 'cannot be written' in capsys.readouterr().out

	cli = mge.MgeCli(_args())
	monkeypatch.setattr(mge.subprocess, 'run', Mock(side_effect = OSError()))
	with pytest.raises(RuntimeError, match = 'returned an error'):
		cli._MgeCli__exec('false')


def test_cli_new_success_and_errors(monkeypatch, tmp_path, capsys):
	cli = mge.MgeCli(_args('new', str(tmp_path / 'existing')))
	(tmp_path / 'existing').mkdir()
	with pytest.raises(SystemExit):
		cli.new()
	assert 'already exists' in capsys.readouterr().out

	cli = mge.MgeCli(_args('new', str(tmp_path / 'missing' / 'endpoint')))
	with pytest.raises(SystemExit):
		cli.new()
	assert 'parent directory' in capsys.readouterr().out

	cli = mge.MgeCli(_args('new', 'not-valid'))
	with pytest.raises(SystemExit):
		cli.new()
	assert 'not valid' in capsys.readouterr().out

	with monkeypatch.context() as context:
		cli = mge.MgeCli(_args('new', 'valid_name'))
		context.setattr(mge.os.path, 'exists', lambda path: False)
		with pytest.raises(SystemExit):
			cli.new()
	assert 'source template' in capsys.readouterr().out

	created = tmp_path / 'created'
	cli = mge.MgeCli(_args('new', str(created)))
	monkeypatch.setattr(cli, '_MgeCli__exec', lambda command: os.system('cp -r cli/new_endpoint_template %s' % created))
	endpoint = _endpoint()
	endpoint.home = str(created)
	monkeypatch.setattr(mge.mg.evidence, 'Endpoint', Mock(return_value = endpoint))
	cli.new()
	conf = (created / 'mge_endpoint.jsonc').read_text()
	assert '"name": "created"' in conf
	assert 'Created a new Endpoint object' in capsys.readouterr().out

	failed = tmp_path / 'failed'
	cli = mge.MgeCli(_args('new', str(failed)))
	monkeypatch.setattr(cli, '_MgeCli__exec', lambda command: os.system('cp -r cli/new_endpoint_template %s' % failed))
	monkeypatch.setattr(mge.mg.evidence, 'Endpoint', Mock(side_effect = ValueError()))
	with pytest.raises(SystemExit):
		cli.new()
	assert 'failed to load' in capsys.readouterr().out


def test_cli_endpoint_commands(monkeypatch, capsys):
	for method in ('summary', 'pilot', 'serve', 'unlock'):
		cli = mge.MgeCli(_args('pilot' if method == 'pilot' else 'serve' if method == 'serve' else method,
			intent = 'READY', port = 8000))
		monkeypatch.setattr(mge.mg.evidence, 'Endpoint', Mock(side_effect = ValueError()))
		with pytest.raises(SystemExit):
			getattr(cli, method)()
		assert 'Could not load' in capsys.readouterr().out

	endpoint = _endpoint(lock = mge.mg.evidence.endpoint.LockState.LOCK_FAILED)
	monkeypatch.setattr(mge.mg.evidence, 'Endpoint', Mock(return_value = endpoint))
	for method in ('pilot', 'serve'):
		cli = mge.MgeCli(_args(method, intent = 'READY', port = 8000))
		with pytest.raises(SystemExit):
			getattr(cli, method)()
		assert 'Could not lock' in capsys.readouterr().out

	endpoint = _endpoint(state_name = None)
	monkeypatch.setattr(mge.mg.evidence, 'Endpoint', Mock(return_value = endpoint))
	cli = mge.MgeCli(_args('pilot', intent = 'READY'))
	cli.pilot()
	endpoint.pilot.assert_called_once_with('READY', just_once = False)
	assert 'no name' in capsys.readouterr().out
	assert endpoint.close.called

	endpoint = _endpoint(state = 1, state_name = 'INITIAL')
	monkeypatch.setattr(mge.mg.evidence, 'Endpoint', Mock(return_value = endpoint))
	cli = mge.MgeCli(_args('serve', intent = 'READY', port = 8000))
	with pytest.raises(SystemExit):
		cli.serve()
	assert 'is in state' in capsys.readouterr().out

	endpoint = _endpoint()
	server = Mock()
	monkeypatch.setattr(mge.mg.evidence, 'Endpoint', Mock(return_value = endpoint))
	monkeypatch.setattr(mge, 'MgeHttpServe', Mock(return_value = server))
	cli = mge.MgeCli(_args('serve', intent = 'ready', port = 8000))
	cli.serve()
	server.serve.assert_called_once_with(8000)
	assert 'Serving the Endpoint' in capsys.readouterr().out

	endpoint = _endpoint(state_name = None)
	server = Mock()
	monkeypatch.setattr(mge.mg.evidence, 'Endpoint', Mock(return_value = endpoint))
	monkeypatch.setattr(mge, 'MgeHttpServe', Mock(return_value = server))
	cli = mge.MgeCli(_args('serve', intent = '100', port = 8000))
	cli.serve()
	assert 'Serving the Endpoint' in capsys.readouterr().out

	endpoint = _endpoint()
	monkeypatch.setattr(mge.mg.evidence, 'Endpoint', Mock(return_value = endpoint))
	cli = mge.MgeCli(_args('unlock'))
	cli.unlock()
	assert endpoint.lock.call_args.args == (mge.mg.evidence.endpoint.LockState.FORCE_FREE,)
	assert 'forcefully unlocked' in capsys.readouterr().out

	cli = mge.MgeCli(_args())
	cli.complete()
	assert 'complete -W' in capsys.readouterr().out


def test_cli_module_dispatch(monkeypatch, tmp_path):
	endpoint = tmp_path / 'endpoint'
	endpoint.mkdir()
	(endpoint / 'mge_endpoint.jsonc').write_text('{}')
	new_endpoint = tmp_path / 'new_endpoint'
	uvicorn_run = Mock()
	monkeypatch.setattr(mge.uvicorn, 'run', uvicorn_run)

	for arguments in [
		['mge', 'new', str(new_endpoint)],
		['mge', 'complete', 'bash'],
		['mge', 'summary', str(endpoint)],
		['mge', 'unlock', str(endpoint)],
		['mge', 'pilot', str(endpoint), '0', '--just_once'],
		['mge', 'serve', str(endpoint), '0', '8000']]:
		monkeypatch.setattr(sys, 'argv', arguments)
		runpy.run_module('cli.mge', run_name = '__main__')

	assert uvicorn_run.called
