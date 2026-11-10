import copy

from enum import Enum


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
	""" The questions a [`Formalizer`][mercury.graph.evidence.Formalizer] can answer. The value of each one is its capability: its name
	(with a `%s` for the name of the Formalizer), its arguments and its output.

	Every question holds all it needs in its arguments. The extracting questions take the 'ontology' (see `ONTOLOGY_PARAMETER`), while
	`match_node` only takes the definition of the type of the mention. Every question also takes, optionally, a 'context'. A question
	is answered by the [`Decider`][mercury.graph.evidence.Decider] configured for it, under the key of its name in lowercase (e.g.,
	"extract_nodes").
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
									   'optionally "texts", a list of texts where it was found.'
					},
					'node': {
						'type': 'object',
						'description': 'A known instance: "id", "description" and optionally "names", its other names.'
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
							'type': 'object'
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


	def key(self):
		""" Returns the key of the question in the configuration of a Formalizer (its name in lowercase, e.g., "extract_nodes"). """

		result = self.name.lower()

		return result


	def capability(self, formalizer_name):
		""" Returns the capability of the question for a Formalizer: a copy of its value with the name of the Formalizer in its name.

		Args:
			formalizer_name (str): The name of the Formalizer (e.g., "GLiNER2").

		Returns:
			(dict): The capability (e.g., named `extract_nodes_GLiNER2`).
		"""

		result	 = copy.deepcopy(self.value)
		function = result['function']

		function['name'] = function['name'] % formalizer_name

		return result
