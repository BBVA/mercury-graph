from .agentic import Agentic


class Agent(Agentic):
	""" Agent is a class that connects to an external LLM using `litellm` and exposes it in the Agentic tree.

	## Overview

	This has two main purposes:

	1. Making the Agent aware of what tools it has access to, and how they work so it can create proper arguments. This is referred
	downstream in the Agentic tree.

	2. Exposing the Agentic interface to the agent in which the Agent answers very specific and well defined queries. Those queries
	are provided by the Endpoint. The Endpoint will typically use Agents to classify user input into known categories. This  is referred
	to as upstream in the Agentic tree.

	## Focus and Scope

	Agents solve minimal problems, ideally they would be simpler models than LLMs if such models could produce correct output from inputs.

	Agents are not aware of the Endpoint architecture, they only "see" what tools are below them in the Agentic tree.

	Agents do not validate, prepare, plan their own tasks. The Endpoint is responsible for creating a graph of Agents (or Agentics)
	that takes care of that.

	These agents do not, in general, communicate through natural language. They use instructions and metadata in natural language but
	produce structured output that may also include natural language.

	## Interfacing with Agents

#TODO: Update as in the notebook that uses tools!

	Agents have a fixed list of capabilities, a fixed number of steps they can use and a list of Agentic services they can call. The first
	thing and Agent must do is match which of its capabilities is required to answer the query. There is always a NOT_FOR_ME placeholder
	that ends a query just as not for the Agent. A supervising Agent can check in an Agent's `meta` if the Agent should be suited to answer
	a query.

	The Agent object exposes the history of the steps in the Agent's prompt. The Agent can either answer the query or ask do a query. In
	case it does a query, the answer will be added to the history.

	"""

	def __init__(self, schema = None, parent = None, logger = None, extra_args = None):
		super().__init__(my_class = 'agent', schema = schema, parent = parent, logger = logger)

		if extra_args is not None:
			self.conf = extra_args
		else:
			self.conf = {}


	def _run(self, request):
		return {'status': 'ok'}


	def _meta(self):
		return {'status': 'ok'}


	def _dry_run(self, request):
		return {'status': 'ok'}
