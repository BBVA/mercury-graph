import pytest

from mercury.graph.evidence import DeciderState
from mercury.graph.evidence.agentic import AgenticRunInvalidRequest, AgenticRunInvalidState
from mercury.graph.evidence.deciders import MatchNodeLayaDecider


class FakeLaya:
	""" Stands for a model loaded by `laya.load()`: it records the calls to `predict()` and answers a fixed result. """

	def __init__(self, score, usage = None):
		self.score = score
		self.usage = usage
		self.calls = []


	def predict(self, state, questions):
		""" Records the call and answers the score as the probability of yes. """
		self.calls.append((state, questions))

		result = {'answers': {'same': {'noul': self.score}}}
		if self.usage is not None:
			result['usage'] = self.usage

		return result


class FakeLoad:
	""" Stands for `laya.load()`: it records its arguments and returns the model, or raises the error. """

	def __init__(self, model = None, error = None):
		self.model = model
		self.error = error
		self.calls = []


	def __call__(self, name, **options):
		self.calls.append((name, options))

		if self.error is not None:
			raise self.error

		return self.model


def _decider(monkeypatch, conf, load, logger = None):
	""" Returns a MatchNodeLayaDecider whose `laya.load()` is `load` (None when Laya is not installed). """
	decider = MatchNodeLayaDecider('Laya', conf, logger = logger)
	monkeypatch.setattr(decider, '_import_load', lambda: load)

	return decider


def _ready_decider(monkeypatch, model, conf = None, logger = None):
	""" Returns a MatchNodeLayaDecider piloted to READY with the fake model. """
	if conf is None:
		conf = {'model': 'convaiinnovations/laya'}

	decider = _decider(monkeypatch, conf, FakeLoad(model), logger = logger)
	decider.pilot(DeciderState.READY.value)

	return decider


def _request(decider, arguments):
	""" Returns a request to the capability of the Decider. """
	name = decider.meta['capabilities'][0]['function']['name']

	return {'name': name, 'arguments': arguments}


def _arguments():
	""" Returns the arguments of a request with only the required fields. """
	mention = {'mention': 'Ms. Ruiz', 'type': 'person|teacher', 'definition': 'A person who teaches at a school.'}
	node	= {'id': 'person|teacher|Elena Ruiz', 'description': 'A science teacher at Riverside High School.'}

	return {'mention': mention, 'node': node}


def test_matchnodelayadecider_capability():
	""" The Decider exposes match_node. """
	decider = MatchNodeLayaDecider('Laya', {'model': 'convaiinnovations/laya'})

	assert decider.question == 'MATCH_NODE'
	assert decider.meta['capabilities'][0]['function']['name'] == 'match_node_Laya'
	assert decider.meta['state'] == DeciderState.INITIAL.value


def test_matchnodelayadecider_pilot_loads_the_model(monkeypatch):
	""" Piloting loads the model with the options that are not null and makes the Decider ready. """
	model = FakeLaya(0.9)
	load  = FakeLoad(model)
	conf  = {'model': 'convaiinnovations/laya', 'subfolder': 'typed-decisions', 'device': None}

	decider = _decider(monkeypatch, conf, load)
	decider.pilot(DeciderState.READY.value)

	assert decider.meta['state'] == DeciderState.READY.value
	assert load.calls == [('convaiinnovations/laya', {'subfolder': 'typed-decisions'})]


def test_matchnodelayadecider_pilot_just_once(monkeypatch):
	""" Piloting just once stops after loading the model. """
	decider = _decider(monkeypatch, {'model': 'convaiinnovations/laya'}, FakeLoad(FakeLaya(0.9)))
	decider.pilot(DeciderState.READY.value, just_once = True)

	assert decider.meta['state'] == DeciderState.MODEL_LOADED_OK.value


@pytest.mark.parametrize('conf, load', [
	({}, FakeLoad(FakeLaya(0.9))),
	({'model': 'convaiinnovations/laya'}, None),
	({'model': 'convaiinnovations/laya'}, FakeLoad(error = OSError('not found')))
])
def test_matchnodelayadecider_pilot_errors(monkeypatch, conf, load):
	""" Without a model, without Laya or when the model fails to load, the Decider logs an error and stays in error state. """
	logger	= []
	decider = _decider(monkeypatch, conf, load, logger = logger)
	decider.pilot(DeciderState.READY.value)

	assert decider.meta['state'] == DeciderState.ERR_MODEL_INIT.value
	assert logger[-1]['type'] == 'error'

	decider.pilot(DeciderState.READY.value)

	assert decider.meta['state'] == DeciderState.ERR_MODEL_INIT.value


@pytest.mark.parametrize('score, threshold, same', [
	(0.7, None, True),
	(0.3, None, False),
	(0.5, None, True),
	(0.7, 0.8, False),
	(0.3, 0.2, True)
])
def test_matchnodelayadecider_run_answers_score_and_same(monkeypatch, score, threshold, same):
	""" The score is the probability of yes, and the mention is the known instance from the threshold on. """
	conf = {'model': 'convaiinnovations/laya'}
	if threshold is not None:
		conf['threshold'] = threshold

	decider	 = _ready_decider(monkeypatch, FakeLaya(score), conf = conf)
	response = decider.run(_request(decider, _arguments()))

	assert response == {'finish_reason': 'stop', 'message': {'score': score, 'same': same}}


def test_matchnodelayadecider_run_sends_the_laya_state(monkeypatch):
	""" Laya gets the known instance, the mention with the definition of its type and the context, in that order. """
	arguments = _arguments()
	arguments['node']['names'] = ['Elena Ruiz', 'Ms. Ruiz']
	arguments['mention']['texts'] = ['Ms. Ruiz took the team to the fair.']
	arguments['context'] = 'The Brookdale Science Fair.'

	model	= FakeLaya(0.9)
	decider = _ready_decider(monkeypatch, model)
	decider.run(_request(decider, arguments))

	laya_state, questions = model.calls[0]

	assert list(laya_state) == ['known_instance', 'mention', 'context']
	assert laya_state['known_instance'] == {
		'id': 'person|teacher|Elena Ruiz',
		'description': 'A science teacher at Riverside High School.',
		'names': ['Elena Ruiz', 'Ms. Ruiz']
	}
	assert laya_state['mention'] == {
		'mention': 'Ms. Ruiz',
		'type': 'person|teacher',
		'type_definition': 'A person who teaches at a school.',
		'texts': ['Ms. Ruiz took the team to the fair.']
	}
	assert laya_state['context'] == 'The Brookdale Science Fair.'
	assert questions == MatchNodeLayaDecider.QUESTIONS


def test_matchnodelayadecider_run_leaves_out_missing_fields(monkeypatch):
	""" The optional fields that the request does not have are not in the state. """
	model	= FakeLaya(0.9)
	decider = _ready_decider(monkeypatch, model)
	decider.run(_request(decider, _arguments()))

	laya_state = model.calls[0][0]

	assert list(laya_state) == ['known_instance', 'mention']
	assert list(laya_state['known_instance']) == ['id', 'description']
	assert list(laya_state['mention']) == ['mention', 'type', 'type_definition']


@pytest.mark.parametrize('usage, logged', [
	(None, False),
	({'truncated': False}, False),
	({'truncated': True, 'state_tokens_dropped': 42}, True)
])
def test_matchnodelayadecider_run_logs_a_cut(monkeypatch, usage, logged):
	""" A state that does not fit the model is logged as a message. """
	logger	= []
	decider = _ready_decider(monkeypatch, FakeLaya(0.9, usage = usage), logger = logger)
	decider.run(_request(decider, _arguments()))

	messages = [event['message'] for event in logger if event['type'] == 'message']

	assert len(messages) == int(logged)
	if logged:
		assert '42 tokens' in messages[0]


def test_matchnodelayadecider_run_invalid_name(monkeypatch):
	""" A request to another function is invalid. """
	decider = _ready_decider(monkeypatch, FakeLaya(0.9))
	request = {'name': 'extract_nodes_Laya', 'arguments': _arguments()}

	with pytest.raises(AgenticRunInvalidRequest):
		decider.run(request)


def test_matchnodelayadecider_run_not_ready():
	""" A Decider that is not ready cannot answer. """
	decider = MatchNodeLayaDecider('Laya', {'model': 'convaiinnovations/laya'})

	with pytest.raises(AgenticRunInvalidState):
		decider.run(_request(decider, _arguments()))


def test_matchnodelayadecider_dry_run():
	""" A dry run accepts the request: the Endpoint validates it. """
	decider = MatchNodeLayaDecider('Laya', {'model': 'convaiinnovations/laya'})

	assert decider.dry_run(_request(decider, _arguments()))['status'] == 0


def test_matchnodelayadecider_close_releases_the_model(monkeypatch):
	""" Closing releases the model. """
	decider = _ready_decider(monkeypatch, FakeLaya(0.9))
	decider.close(endpoint_locked = False)

	assert decider._model is None
