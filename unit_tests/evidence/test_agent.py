import builtins
import importlib

import pytest

from mercury.graph.evidence import Agent
from mercury.graph.evidence import agent as agent_module
from mercury.graph.evidence.agentic import AgenticRunFailed, AgenticRunInvalidRequest, AgenticRunInvalidState


class Tool:
	"""Provides the minimum Agentic interface needed by Agent tool discovery."""

	def __init__(self, tool_id, meta):
		"""Stores a tool ID and its metadata dictionary."""
		self.id = tool_id
		self.meta = meta


class CompletionResult:
	"""Provides the completion result shape returned by litellm."""

	def __init__(self, choice):
		"""Stores one completion choice."""
		self.choices = [choice]


def agent_conf(**extra):
	"""Returns a valid, minimal Agent configuration, extended with extra values."""
	conf = {
		'description': 'Test agent.',
		'upstream': {'name': 'test_agent', 'description': 'Test the agent.'},
		'completion': {'model': 'test/model'}
	}
	conf.update(extra)

	return conf


def test_agent_metadata_and_invalid_setup():
	"""Verifies construction metadata, capability creation, and invalid setup handling."""
	logger = []
	bad = Agent(schema = 'bad', extra_args = {}, logger = logger)

	assert bad.meta['state'] == bad.states.ERR_SETUP.value
	assert bad.meta['capabilities'] == []
	bad.pilot(bad.states.READY.value)
	assert len(logger) == 2

	agent = Agent(schema = 'any', extra_args = agent_conf(description = ['Test', 'agent.']))

	assert type(agent) is Agent
	assert agent.conf['completion'] == {'model': 'test/model'}
	assert agent.meta['state'] == agent.states.INITIAL.value
	assert agent.meta['description'] == 'Test\nagent.'
	assert agent.meta['capabilities'][0]['function']['name'] == 'test_agent'
	assert agent.dry_run({'cmd': 'test'}) == {'status': 0, 'description': 'Valid request.'}


def test_agent_pilot_states_and_tools(monkeypatch):
	"""Verifies incremental setup, unavailable completion, and valid tool discovery."""
	monkeypatch.setattr(agent_module, 'completion', lambda **kwargs: None)
	agent = Agent(schema = 'any', extra_args = agent_conf(you_are = ['You are', 'helpful.'], you_must = 'Answer briefly.'))

	agent.pilot(agent.states.READY.value, just_once = True)
	assert agent.meta['state'] == agent.states.SETUP_OK.value
	assert agent.you_are == {'role': 'system', 'content': 'You are\nhelpful.'}
	assert agent.you_must == {'role': 'developer', 'content': 'Answer briefly.'}
	agent.pilot(agent.states.READY.value, just_once = True)
	assert agent.meta['state'] == agent.states.COMPLETION_OK.value
	agent.pilot(agent.states.READY.value, just_once = True)
	assert agent.meta['state'] == agent.states.READY.value

	empty_system = Agent(schema = 'empty_system', extra_args = agent_conf(you_are = '', you_must = ['Be', 'brief.']))
	empty_system.pilot(empty_system.states.READY.value, just_once = True)
	assert empty_system.you_are is None
	assert empty_system.you_must == {'role': 'developer', 'content': 'Be\nbrief.'}

	empty_developer = Agent(schema = 'empty_developer', extra_args = agent_conf(you_must = ''))
	empty_developer.pilot(empty_developer.states.READY.value, just_once = True)
	assert empty_developer.you_must is None

	capability = {'type': 'function', 'function': {'name': 'tool'}}
	with_tool = Agent(schema = 'tools', extra_args = agent_conf())
	with_tool.add_tool(Tool('tool_id', {'capabilities': [capability]}))
	with_tool.pilot(with_tool.states.READY.value)
	assert with_tool.completion['tools'] == [capability]

	monkeypatch.setattr(agent_module, 'completion', None)
	missing_completion = Agent(schema = 'missing', extra_args = agent_conf())
	missing_completion.pilot(missing_completion.states.READY.value)
	assert missing_completion.meta['state'] == missing_completion.states.ERR_COMPLETION.value

	missing_config = Agent(schema = 'config', extra_args = agent_conf())
	del missing_config.conf['completion']
	missing_config.pilot(missing_config.states.READY.value)
	assert missing_config.meta['state'] == missing_config.states.ERR_SETUP.value


@pytest.mark.parametrize('meta', [{'state': 0}, {'capabilities': [{'type': 'invalid'}]}])
def test_agent_pilot_rejects_invalid_tools(monkeypatch, meta):
	"""Verifies tool discovery rejects missing and malformed capabilities."""
	monkeypatch.setattr(agent_module, 'completion', lambda **kwargs: None)
	agent = Agent(schema = 'tools', extra_args = agent_conf())
	agent.add_tool(Tool('bad_tool', meta))

	agent.pilot(agent.states.READY.value)

	assert agent.meta['state'] == agent.states.ERR_BUILDING_TOOLS.value


def test_agent_run_requests_and_failures(monkeypatch):
	"""Verifies requests, generated messages, invalid requests, and completion failures."""
	calls = []

	def complete(**kwargs):
		"""Records completion arguments and returns a choice."""
		calls.append(kwargs)
		return CompletionResult({'content': 'answer'})

	monkeypatch.setattr(agent_module, 'completion', complete)
	agent = Agent(schema = 'run', extra_args = agent_conf(you_are = 'System.', you_must = 'Developer.'))

	with pytest.raises(AgenticRunInvalidState):
		agent.run({'name': 'test_agent', 'arguments': {'messages': []}})

	agent.pilot(agent.states.READY.value)
	assert agent.run({'name': 'test_agent', 'arguments': {'messages': [{'role': 'user', 'content': 'given'}]}}) == {'content': 'answer'}
	assert calls[-1]['messages'] == [{'role': 'user', 'content': 'given'}]
	assert agent.run({'name': 'test_agent', 'arguments': {'query': 'generated'}}) == {'content': 'answer'}
	assert calls[-1]['messages'] == [
		{'role': 'system', 'content': 'System.'},
		{'role': 'developer', 'content': 'Developer.'},
		{'role': 'user', 'content': 'generated'}
	]

	with pytest.raises(AgenticRunInvalidRequest):
		agent.run({'name': 'other', 'arguments': {'messages': []}})
	with pytest.raises(AgenticRunInvalidRequest):
		agent.run({'name': 'test_agent', 'arguments': {'first': 1, 'second': 2}})

	def fail(**kwargs):
		"""Raises the error reported by a failed completion service."""
		raise RuntimeError('unavailable')

	monkeypatch.setattr(agent_module, 'completion', fail)
	with pytest.raises(AgenticRunFailed):
		agent.run({'name': 'test_agent', 'arguments': {'messages': []}})
	assert agent.meta['state'] == agent.states.ERR_COMPLETION.value


def test_agent_handles_missing_litellm_import(monkeypatch):
	"""Verifies importing Agent tolerates an unavailable optional litellm dependency."""
	original_import = builtins.__import__

	def import_without_litellm(name, *args, **kwargs):
		"""Raises ImportError only for litellm imports."""
		if name == 'litellm':
			raise ImportError('litellm unavailable')

		return original_import(name, *args, **kwargs)

	monkeypatch.setattr(builtins, '__import__', import_without_litellm)
	importlib.reload(agent_module)
	assert agent_module.completion is None
	monkeypatch.undo()
	importlib.reload(agent_module)


# if __name__ == "__main__":
# 	pytest.main([__file__])
