from copy import deepcopy
from enum import Enum

from .agentic import Agentic
from .agentic_graph import AgenticGraph


class DeciderState(Enum):
	""" The `DeciderState` is an enumeration that defines all possible states of a Decider. """

	ERR_MODEL_INIT		= -1	# Something failed loading the model.

	INITIAL				=  0	# The initial state of the decider.
	MODEL_LOADED_OK		=  1	# The model was loaded successfully.

	READY				=  100	# The decider is ready to be queried.


ONTOLOGY_PARAMETER = {
	'type': 'object',
	'description': 'The ontology, or the part of it to use: "types", a list of {"id", "definition"} (e.g., "person|teacher"), and '
				   '"relations", a list of {"id", "src", "dst", "definition"}.'
}

CONTEXT_PARAMETER = {
	'type': 'array',
	'items': {
		'type': 'object'
	},
	'description': 'Optional context of the question (e.g., where the text comes from), built by the caller.'
}


class Question(Enum):
	""" The questions a [`Decider`][mercury.graph.evidence.Decider] can answer.

	It is an enumeration of capabilities a Decider must expose. They are identified by a key (such as `EXTRACT_NODES`) and you can
	create a valid capability by calling the `capability()` method with this key and the name of the Decider.

	The capabilities are in the format expected by the Agentic interface which is also usable as tools by the OpenAI/litellm API.
	"""

	EXTRACT_NODES = {
		'type': 'function',
		'function': {
			'name': 'extract_nodes_%s',
			'description': 'Identify the mentions of the types of an ontology in a text.',
			'parameters': {
				'type': 'object',
				'properties': {
					'text': {
						'type': 'string',
						'description': 'Text from which to identify nodes.'
					},
					'ontology': ONTOLOGY_PARAMETER,
					'context': CONTEXT_PARAMETER
				},
				'required': ['text', 'ontology']
			},
			'returns': {
				'type': 'array',
				'items': {
					'type': 'object',
					'description': 'One node per mention, with "mention" (the text as it appears), "type" and "confidence".'
				}
			}
		}
	}

	MATCH_NODE = {
		'type': 'function',
		'function': {
			'name': 'match_node_%s',
			'description': 'Decide whether a mention is a known instance (a node, as a "type|name" id).',
			'parameters': {
				'type': 'object',
				'properties': {
					'mention': {
						'type': 'object',
						'description': 'A mention: "mention" (the text as it appears), "type", "definition" (that of its type in the ontology) and '
									   'optionally "texts", a list of texts where it was found.',
						'required': ['mention', 'type', 'definition']
					},
					'node': {
						'type': 'object',
						'description': 'A known instance: "id", "description" and optionally "names", its other names.',
						'required': ['id', 'description']
					},
					'context': CONTEXT_PARAMETER
				},
				'required': ['mention', 'node']
			},
			'returns': {
				'type': 'object',
				'description': '"score" (0..1), how likely the mention is the known instance, and "same", whether it is.'
			}
		}
	}

	EXTRACT_EDGES = {
		'type': 'function',
		'function': {
			'name': 'extract_edges_%s',
			'description': 'Identify the edges of the relations of an ontology between the nodes of a text.',
			'parameters': {
				'type': 'object',
				'properties': {
					'text': {
						'type': 'string',
						'description': 'Text from which to identify edges.'
					},
					'nodes': {
						'type': 'array',
						'items': {
							'type': 'object',
							'required': ['mention', 'id']
						},
						'description': 'The nodes of the text, with "mention" and "id".'
					},
					'ontology': ONTOLOGY_PARAMETER,
					'context': CONTEXT_PARAMETER
				},
				'required': ['text', 'nodes', 'ontology']
			},
			'returns': {
				'type': 'array',
				'items': {
					'type': 'object',
					'description': 'One edge with "src", "relation", "dst" (ids) and "confidence".'
				}
			}
		}
	}


	@classmethod
	def capability(cls, question, name):
		""" Returns the capability for a valid question key completed with the given name.

		Args:
			question (str): The key of the question to get the capability for. E.g. 'EXTRACT_EDGES'
			name (str): The name to complete the capability with. E.g. 'my_decider' makes the previous example 'extract_edges_my_decider'.

		Returns:
			(dict): The capability dictionary for the given question and name. Or None if the question key is invalid.
		"""
		member = cls.__members__.get(question)
		if not member:
			return None

		capability = deepcopy(member.value)
		capability['function']['name'] = capability['function']['name'] % name

		return capability


class Decider(Agentic):
	""" A Decider answers one specific type of question of those enumerated in the Question class.

	## Overview

	It is typically a wrapper serializing the I/O and calling an ML model. It is the model that answers one of the questions in Question.
	You can have any number of Deciders in an Endpoint (from evidence.deciders of custom implementations). Each Formalizer only
	supports one or none Decider for each of the questions. An EvidenceGraph only supports one Formalizer. An Endpoint supports
	any number of EvidenceGraphs. The Endpoint can also expose the capabilities of any of the Deciders if configured to do so.

	## Implementing a Decider

	This minimalistic class is abstract because it does not implement the mandatory `_run()` and `_dry_run()` methods of Agentic.

	It does implement the `_meta()` method and a constructor that probably does anything the subclass needs except setting self.question
	to the key of the question it answers. After setting `self.question`, the subclass can call `self._meta_ = self._meta()` to update
	its capabilities. The subclass has to implement the `_run()` and `_dry_run()` and possibly `pilot()` unless it does not have
	any initialization and can use the always ready state provided by Agentic.

	## Using a Decider

	A Decider is just an Agentic defined in the configuration of an Endpoint. When the Endpoint loads the decider, it will provide it
	with the appropriate extra arguments for its constructor. The Decider has to implement its own `pilot()` method that checks
	for library imports, models, etc. and sets its state to either DeciderState.READY or DeciderState.FAILED.

	The Decider will be called as a tool by a Formalizer that includes its name for one of its functions.

	Args:
		schema (str): a schema (a unique name) to use for the Decider's ID.
		extra_args (dict): the configuration for the Decider.
		endpoint (Agentic): an optional Endpoint. It becomes part of the Decider's ID and is available via `self.endpoint`. If not
			provided, the Decider becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(my_class = 'decider', schema = schema, endpoint = endpoint, logger = logger)

		if schema is None:			# This allows finding out the class name (to link tools) without actually instantiating a full object.
			return

		self.states = DeciderState

		self.conf = extra_args
		self.name = schema
		self.question = None		# This must be overridden by subclasses.

		self._meta_ = self._meta()	# Just to make .meta reflect the initial state.


	def _meta(self):
		""" Returns the metadata of the Agent.

			(See [`Agentic.meta()`][mercury.graph.evidence.Agentic.meta].)
		"""

		meta = {}
		meta['state'] = DeciderState.INITIAL.value

		meta['description'] = self.conf.get('description', '')
		if type(meta['description']) is list:
			meta['description'] = '\n'.join(meta['description'])

		meta['capabilities'] = []

		cap = Question.capability(self.question, self.name)
		if cap is not None:
			meta['capabilities'].append(cap)

		return meta
