import json, os
import re
import shutil

import pytest

from mercury.graph.evidence import Endpoint
from mercury.graph.evidence.endpoint import LockState


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
	assert 'reader: unknown' in clean
	assert 'gru: unknown' in clean


def test_json_load(tmp_path):
	fn = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'cli', 'new_endpoint_template'))

	path = str(tmp_path / 'endpoint_a')

	os.makedirs(path)

	os.system('cp %s/* %s/' % (fn, path))

	ep = Endpoint(path)

	assert ep.state_name(100) == 'READY'

	txt = str(ep)

	assert 'READY' in txt

	ep._meta_['state'] = 999

	txt = str(ep)

	assert 'no name' in txt

	ep.pilot(0)

	assert len(ep.conf['agents']) > 1

	with open('%s/ontologies.jsonc' % path, 'w') as f:
		json.dump({'loop': {'$ref': './ontologies.jsonc'}}, f)

	with pytest.raises(ValueError):
		ep = Endpoint(path)


# if __name__ == "__main__":
# 	pytest.main([__file__])
