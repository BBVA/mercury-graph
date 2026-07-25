import json, os, pickle, re

from unittest.mock import Mock

import pytest

from mercury.graph.evidence import Endpoint
from mercury.graph.evidence.agentic import AgenticRunInvalidState
from mercury.graph.evidence.endpoint import EndPointState, LockState

import mercury.graph.evidence.endpoint as endpoint_module


def _endpoint_conf():
	return {
		'sources': {},
		'ontologies': {},
		'formalizers': {},
		'evidence_graphs': {},
		'agents': {},
		'custom_agentics': {}
	}


def _make_endpoint(tmp_path, name = 'endpoint', conf = None, logger = None):
	path = tmp_path / name
	path.mkdir()
	if conf is None:
		conf = _endpoint_conf()
	with open(path / 'mge_endpoint.jsonc', 'w') as f:
		json.dump(conf, f)
	return Endpoint(str(path), logger = logger)


def test_endpoint_lock(tmp_path):
	with pytest.raises(ValueError):
		Endpoint('NOT@existent.path')

	path = tmp_path / 'test_endpoint'

	os.makedirs(path)

	with pytest.raises(ValueError):	# The file "mge_endpoint.jsonc" is missing.
		Endpoint(str(path))

	conf = {'key': 'value'}

	with open(path / 'mge_endpoint.jsonc', 'w') as f:
		json.dump(conf, f)

	endpoint = Endpoint(str(path))

	assert endpoint.lock(LockState.INIT_IF_NONE) == LockState.FREE
	assert endpoint.lock(LockState.LOCK) == LockState.LOCK
	assert endpoint.lock(LockState.INIT_IF_NONE) == LockState.LOCK
	assert endpoint.lock(LockState.LOCK) == LockState.LOCK_FAILED
	assert endpoint.lock(LockState.INIT_IF_NONE) == LockState.LOCK
	assert endpoint.lock(LockState.FREE) == LockState.FREE
	assert endpoint.lock(LockState.INIT_IF_NONE) == LockState.FREE
	assert endpoint.lock(LockState.FREE) == LockState.FREE
	assert endpoint.lock(LockState.INIT_IF_NONE) == LockState.FREE

	os.remove(endpoint.free_fn)

	assert endpoint.lock(LockState.FREE) == LockState.FREE_FAILED

	assert endpoint.lock(LockState.FORCE_FREE) == LockState.FREE
	assert endpoint.lock(LockState.LOCK) == LockState.LOCK
	assert endpoint.lock(LockState.FREE) == LockState.FREE

	assert endpoint.lock(LockState.FORCE_FREE) == LockState.FREE
	assert endpoint.lock(LockState.LOCK) == LockState.LOCK
	assert endpoint.lock(LockState.FORCE_FREE) == LockState.FREE

	with pytest.raises(ValueError):
		endpoint.lock('what?')


def test_dummy_runs(tmp_path):
	path = tmp_path / 'dummy'

	os.makedirs(path)

	conf = {'key': 'value'}

	with open(path / 'mge_endpoint.jsonc', 'w') as f:
		json.dump(conf, f)

	endpoint = Endpoint(str(path))

	with pytest.raises(AgenticRunInvalidState):
		endpoint.run({'query': 'dummy'})

	endpoint.dry_run({'query': 'dummy'})
	assert type(endpoint.meta) == dict


def test_endpoint_str(tmp_path):
	path = tmp_path / 'endpoint_str'

	os.makedirs(path)

	conf = {
		'name': 'demo_endpoint',
		'creation_date': '2026-07-18',
		'mge_version': '1.2.3',
		'description': 'A console friendly endpoint summary.',
		'state_names': {
			'initial': 0,
			'ready': 100
		},
		'sources': {},
		'ontologies': {},
		'formalizers': {},
		'evidence_graphs': {},
		'agents': {
			'reader': {
				'name': 'reader',
				'state': 100
			},
			'gru': {
				'name': 'gru'
			}
		}
	}

	with open(path / 'mge_endpoint.jsonc', 'w') as f:
		json.dump(conf, f)

	endpoint = Endpoint(str(path))
	txt = str(endpoint)
	clean = re.sub(r'\033\[[0-9;]*m', '', txt)

	assert 'Endpoint' in clean.splitlines()[0]
	assert 'demo_endpoint' in txt
	assert '2026-07-18' in txt
	assert '1.2.3' in txt
	assert 'A console friendly endpoint summary.' in txt
	assert 'sources (0 total)' in clean
	assert 'ontologies (0 total)' in clean
	assert 'formalizers (0 total)' in clean
	assert 'evidence_graphs (0 total)' in clean
	assert 'agents (2 total)' in clean
	assert 'state' in clean
	assert 'reader:' in clean
	assert 'gru:' in clean


def test_json_load(tmp_path):
	fn = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'cli', 'new_endpoint_template'))

	path = str(tmp_path / 'endpoint_a')

	os.makedirs(path)

	os.system('cp %s/* %s/' % (fn, path))

	ep = Endpoint(path)

	assert ep.state_name(100) == 'ALL_READY'

	txt = str(ep)

	assert 'Endpoint' in txt

	ep._meta_['state'] = 999

	txt = str(ep)

	assert 'no name' in txt

	ep.pilot(0)

	assert len(ep.conf['agents']) > 1

	with open('%s/ontologies.jsonc' % path, 'w') as f:
		json.dump({'loop': {'$ref': './ontologies.jsonc'}}, f)

	with pytest.raises(ValueError):
		ep = Endpoint(path)


def test_endpoint_auto_pilot_and_close(tmp_path, monkeypatch):
	conf = _endpoint_conf()
	conf['auto_pilot'] = {'file_name': 'state.pickle'}
	logger = []
	path = tmp_path / 'auto_endpoint'
	path.mkdir()
	with open(path / 'mge_endpoint.jsonc', 'w') as f:
		json.dump(conf, f)
	with open(path / 'state.pickle', 'wb') as f:
		pickle.dump({'state': 1}, f)

	piloted = []
	monkeypatch.setattr(Endpoint, 'pilot', lambda self, intent, just_once = False: piloted.append(intent))
	endpoint = Endpoint(str(path), logger = logger)

	assert piloted == [1]
	assert 'Auto-piloting' in logger[0]['message']

	agentic = Mock()
	agentic.id = 'agentic'
	endpoint.tools = {'agentic': agentic}
	endpoint.close(False)
	assert agentic.close.call_args.args == (False,)

	endpoint.close(True)
	conf['auto_save'] = {'file_name': 'saved.pickle', 'save': ['state']}
	endpoint.conf = conf
	endpoint.meta['state'] = 42
	endpoint.close(True)
	with open(path / 'saved.pickle', 'rb') as f:
		assert pickle.load(f) == {'state': 42}


def test_endpoint_str_loaded_objects_and_capabilities(tmp_path):
	endpoint = _make_endpoint(tmp_path, 'str_loaded')
	endpoint.conf['agents'] = {'empty': {}, 'unknown': {}, 'ready': {}}
	endpoint._meta_ = {'state': 0, 'capabilities': [{'function': {'name': 'capability'}}]}
	endpoint.agentic_by_capability = {'capability': Mock()}

	empty = Mock()
	empty.id = 'empty_id'
	empty.meta = {}
	unknown = Mock()
	unknown.id = 'unknown_id'
	unknown.meta = {'state': 99}
	unknown.state_name.return_value = None
	ready = Mock()
	ready.id = 'ready_id'
	ready.meta = {'state': 100}
	ready.state_name.return_value = 'ALL_READY'
	endpoint.ids['agents'] = {'empty': empty.id, 'ready': ready.id, 'unknown': unknown.id}
	endpoint.tools = {empty.id: empty, ready.id: ready, unknown.id: unknown}

	text = re.sub(r'\033\[[0-9;]*m', '', str(endpoint))
	assert 'capabilities  : (1 total)' in text
	assert 'empty: no state' in text
	assert 'unknown: 99 (no name)' in text
	assert 'ready: 100 (ALL_READY)' in text


def test_endpoint_dry_run_request_issues(tmp_path, monkeypatch):
	endpoint = _make_endpoint(tmp_path, 'dry_run')
	endpoint.meta['state'] = EndPointState.ALL_READY.value

	monkeypatch.setattr(endpoint, '_request_issues', lambda request: None)
	assert endpoint.dry_run({}) == {'status': 0, 'description': 'Valid request.'}
	monkeypatch.setattr(endpoint, '_request_issues', lambda request: 'bad request')
	assert endpoint.dry_run({}) == {'status': 2, 'description': 'bad request'}
	assert Endpoint._request_issues(endpoint, {}) is None


def test_endpoint_pilot_states(tmp_path, monkeypatch):
	endpoint = _make_endpoint(tmp_path, 'pilot_states')
	endpoint.meta['state'] = EndPointState.ERR_LOADING_OBJ.value
	endpoint.pilot(EndPointState.ALL_READY.value)
	assert endpoint.meta['state'] == EndPointState.ERR_LOADING_OBJ.value

	endpoint.meta['state'] = EndPointState.INITIAL.value
	monkeypatch.setattr(endpoint, '_load_objects', lambda: False)
	endpoint.pilot('LOADED_OBJ')
	assert endpoint.meta['state'] == EndPointState.ERR_LOADING_OBJ.value

	endpoint.meta['state'] = EndPointState.INITIAL.value
	monkeypatch.setattr(endpoint, '_load_objects', lambda: True)
	monkeypatch.setattr(endpoint, '_link_objects', lambda: False)
	endpoint.pilot(EndPointState.LINKED_OBJ.value)
	assert endpoint.meta['state'] == EndPointState.ERR_LINKING.value

	endpoint.meta['state'] = EndPointState.INITIAL.value
	monkeypatch.setattr(endpoint, '_link_objects', lambda: True)
	monkeypatch.setattr(endpoint, '_expose_api', lambda: False)
	endpoint.pilot(EndPointState.EXPOSED_API.value)
	assert endpoint.meta['state'] == EndPointState.ERR_EXPOSING.value

	endpoint.meta['state'] = EndPointState.INITIAL.value
	monkeypatch.setattr(endpoint, '_expose_api', lambda: True)
	endpoint.pilot(EndPointState.EXPOSED_API.value)
	assert endpoint.meta['state'] == EndPointState.EXPOSED_API.value

	agentic = Mock()
	agentic.meta = {'state': 0}
	endpoint.meta['state'] = EndPointState.EXPOSED_API.value
	monkeypatch.setattr(endpoint, '_next_agentic_below', Mock(side_effect = [agentic, None]))
	endpoint.pilot(EndPointState.ALL_READY.value)
	assert endpoint.meta['state'] == EndPointState.ALL_READY.value

	endpoint.meta['state'] = EndPointState.EXPOSED_API.value
	agentic.meta = {'state': -1}
	monkeypatch.setattr(endpoint, '_next_agentic_below', lambda intent: agentic)
	endpoint.pilot(EndPointState.ALL_READY.value)
	assert endpoint.meta['state'] == EndPointState.ERR_IN_OBJECT.value

	endpoint.meta['state'] = EndPointState.EXPOSED_API.value
	agentic.meta = {'state': 0}
	monkeypatch.setattr(endpoint, '_next_agentic_below', Mock(side_effect = [agentic, agentic]))
	endpoint.pilot(50, just_once = True)
	assert endpoint.meta['state'] == EndPointState.PILOT_REQUIRED.value


def test_endpoint_load_objects(tmp_path):
	conf = _endpoint_conf()
	conf['sources'] = {'source': {'name': 'source', 'extra_args': {'nested': {'$path': 'source'}}}}
	conf['ontologies'] = {'ontology': {'name': 'ontology', 'extra_args': {}}}
	conf['formalizers'] = {'formalizer': {'name': 'formalizer', 'extra_args': {}}}
	conf['evidence_graphs'] = {'graph': {'name': 'graph', 'extra_args': {}}}
	conf['agents'] = {'agent': {'name': 'agent', 'extra_args': {}}}
	conf['custom_agentics'] = {'custom': {'name': 'custom', 'class_name': 'Custom', '$path': 'custom.py', 'extra_args': {}}}
	endpoint = _make_endpoint(tmp_path, 'load_objects', conf)
	custom = tmp_path / 'load_objects' / 'custom.py'
	custom.write_text(
		'from mercury.graph.evidence.agentic import Agentic\n'
		'class Custom(Agentic):\n'
		'\tdef __init__(self, schema, extra_args, endpoint=None, logger=None):\n'
		'\t\tsuper().__init__(my_class="custom", schema=schema, endpoint=endpoint, logger=logger)\n'
		'\tdef _run(self, request): return {}\n'
		'\tdef _meta(self): return {"state": 0}\n'
		'\tdef _dry_run(self, request): return {}\n'
	)

	assert endpoint._load_objects() is True
	assert set(endpoint.ids) == set(conf)
	assert endpoint.tools[endpoint.ids['sources']['source']].conf['nested']['path'].endswith('/source')
	assert endpoint.ids['custom_agentics']['custom'] in endpoint.tools


def test_endpoint_load_objects_errors(tmp_path, monkeypatch):
	conf = _endpoint_conf()
	conf['custom_agentics'] = {'custom': {'name': 'custom', 'class_name': 'Custom', '$path': 'custom.py'}}
	endpoint = _make_endpoint(tmp_path, 'invalid_custom', conf)
	(tmp_path / 'invalid_custom' / 'custom.py').write_text('class Custom: pass\n')
	assert endpoint._load_objects() is False

	conf = _endpoint_conf()
	conf['custom_agentics'] = {'custom': {'name': 'custom', 'class_name': 'Custom', '$path': 'custom.py'}}
	endpoint = _make_endpoint(tmp_path, 'missing_spec', conf)
	monkeypatch.setattr(endpoint_module.importlib.util, 'spec_from_file_location', lambda name, path: None)
	assert endpoint._load_objects() is False

	class DuplicateID:
		def __init__(self, schema, extra_args, endpoint = None, logger = None):
			self.id = 'duplicate'

	monkeypatch.setattr(endpoint_module, 'Source', DuplicateID)
	monkeypatch.setattr(endpoint_module, 'AgenticGraph', DuplicateID)
	conf = _endpoint_conf()
	conf['sources'] = {'source': {'name': 'source'}}
	conf['ontologies'] = {'ontology': {'name': 'ontology'}}
	endpoint = _make_endpoint(tmp_path, 'duplicate_id', conf)
	assert endpoint._load_objects() is False

	conf = _endpoint_conf()
	conf['sources'] = {
		'one': {'name': 'same'},
		'two': {'name': 'same'}
	}
	endpoint = _make_endpoint(tmp_path, 'duplicate_name', conf)
	assert endpoint._load_objects() is False


def test_endpoint_link_objects(tmp_path):
	endpoint = _make_endpoint(tmp_path, 'link_objects')

	def add_agentic(name, id):
		agentic = Mock()
		agentic.id = id
		agentic.add_tool = Mock()
		endpoint.tools[id] = agentic
		endpoint.ids['agents'][name] = id
		return agentic

	endpoint.tools = {}
	a = add_agentic('a', 'a_id')
	b = add_agentic('b', 'b_id')
	endpoint.conf['agents'] = {'a': {'tools': ['b']}, 'b': {'tools': []}}
	assert endpoint._link_objects() is True
	a.add_tool.assert_called_once_with(b)

	endpoint.ids['agents'] = {'a': 'a_id'}
	endpoint.conf['agents'] = {'a': {'tools': ['missing']}}
	assert endpoint._link_objects() is False

	endpoint.ids['agents'] = {'a': 'a_id', 'b': 'b_id'}
	endpoint.conf['agents'] = {'a': {'tools': ['b']}, 'b': {'tools': ['a']}}
	assert endpoint._link_objects() is False

	endpoint.ids = _endpoint_conf()
	endpoint.tools = {'a_id': a, 'b_id': b}
	endpoint.ids['sources'] = {'a': 'a_id'}
	endpoint.ids['agents'] = {'a': 'b_id'}
	assert endpoint._link_objects() is False


def test_endpoint_expose_api(tmp_path):
	endpoint = _make_endpoint(tmp_path, 'expose_api')
	agentic = Mock()
	agentic.id = 'agentic'
	endpoint.name_to_agentic = {'agentic': agentic}

	for expose in (None, []):
		endpoint.conf['expose'] = expose
		assert endpoint._expose_api() is False

	endpoint.conf['expose'] = ['missing']
	assert endpoint._expose_api() is False

	for capabilities in (None, [{'function': 'invalid'}], [{'function': {'name': 'not valid'}}]):
		agentic.meta = {} if capabilities is None else {'capabilities': capabilities}
		endpoint.conf['expose'] = ['agentic']
		assert endpoint._expose_api() is False

	agentic.meta = {'capabilities': [{'function': {'name': 'same'}}]}
	other = Mock()
	other.id = 'other'
	other.meta = {'capabilities': [{'function': {'name': 'same'}}]}
	endpoint.name_to_agentic['other'] = other
	endpoint.conf['expose'] = ['agentic', 'other']
	assert endpoint._expose_api() is False

	agentic.meta = {'capabilities': [{'function': {'name': 'first'}}, {'function': {'name': 'second'}}]}
	endpoint.conf['expose'] = ['agentic']
	assert endpoint._expose_api() is True
	assert list(endpoint.agentic_by_capability) == ['first', 'second']


def test_endpoint_next_agentic_below(tmp_path):
	endpoint = _make_endpoint(tmp_path, 'next_agentic')
	below = Mock()
	below.meta = {'state': 1}
	above = Mock()
	above.meta = {'state': 100}
	endpoint.tools = {'below': below, 'above': above}

	assert endpoint._next_agentic_below(2) is below
	below.meta['state'] = 2
	assert endpoint._next_agentic_below(2) is None


# if __name__ == "__main__":
# 	pytest.main([__file__])
