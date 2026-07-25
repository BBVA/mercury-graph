from .agentic import Agentic, AgenticRunInvalidState, AlwaysReadyState


class Agent(Agentic):
	""" Agent is a class that connects to an external LLM using `litellm` and exposes it in the Agentic tree.

	## Overview

	This connects the LLM model is two ways: Upstream and Downstream.

	1. Upstream: It exposes the Agent's capabilities (defined in the Agents configuration) via an Agentic interface to any Agentic in
	its Endpoint that can use it as a tool.

	2. Downstream: Making the Agent aware of what tools it has access to, and how they work so it can create proper arguments.

	## Focus and Scope

	Agents solve minimal problems, ideally they would be simpler models than LLMs if such models could produce correct output from inputs.

	Agents are not aware of the Endpoint architecture, they only "see" what tools have been provided to them via `add_tool()`.

	Agents do not validate, prepare, plan their own tasks. The Endpoint is responsible for the "higher-level" orchestration.

	These agents do not, in general, communicate through natural language. They use instructions and metadata in natural language but
	produce structured output that may or may not include natural language.

	## Interfacing with Agents

	Agents have a fixed list of capabilities. Any accounting of resources for answering a query belongs to the Endpoint. Agents do not
	directly call a tool. Instead, they produce a litellm (OpenAI-style) answer with `finish_reason='tool_calls'` and
	`tool_calls=[ChatCompletionMessageToolCall(function=Function(arguments='{"input": 16}', name='my_tool_for_sqrt')`. The Endpoint
	calls the tools if the "accounting" of resources is valid and calls the Agent back with result properly appended to the Agent's
	conversation.

	## Defining an Agent

	Agents are defined entirely by their configuration (model, capabilities and tools). Note that all capabilities in an Agent can
	use all tools. If you want to restrict tool availability, just define more Agents. Agents are intentionally "narrow" in scope.
	You can use as many as you want, either exposing them in the Endpoint or letting another Agent use them as a tool.

	Args:
		schema (str): a schema (a unique name) to use for the Agent's ID.
		extra_args (dict): the configuration for the Agent.
		endpoint (Agentic): an optional Endpoint to use for the Agent's ID.
		logger: an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(my_class = 'agent', schema = schema, endpoint = endpoint, logger = logger)

		self.conf = extra_args

		self.pilot(AlwaysReadyState.READY.value)	# This forces a call to _meta() to check the configuration.


	def _run(self, request):
		""" Runs the Agent with the given request.

			(See [`Agentic.run()`](./#mercury.graph.evidence.Agentic.run))
		"""
		raise AgenticRunInvalidState


	def _meta(self):
		meta = {'state' : AlwaysReadyState.CONSTRUCTION_FAILED.value}

		if self.conf is None or 'api_base' not in self.conf or 'capabilities' not in self.conf or 'model_name' not in self.conf:
			return meta

		meta['capabilities'] = self.conf['capabilities']
		meta['state'] = AlwaysReadyState.READY.value

		return meta


	def _dry_run(self, request):
		""" Simulates running the Agent with the given request.

			(See [`Agentic.dry_run()`](./#mercury.graph.evidence.Agentic.dry_run))
		"""
		return {'status': 1, 'description': 'Not ready.'}
