from copy import deepcopy
from enum import Enum

from .agentic import Agentic, AgenticRunInvalidRequest
from .agentic_graph import AgenticGraph
from .decider import CONTEXT_PARAMETER, Decider, DeciderState


class FormalizerState(Enum):
	""" The `FormalizerState` is an enumeration that defines all possible states of a Formalizer. """

	ERR_DECIDER_INIT	= -2	# Something failed loading the deciders.
	ERR_ONTOLOGY_INIT	= -1	# Something failed loading the ontology.

	INITIAL				=  0	# The initial state of the formalizer.
	ONTOLOGY_LOADED_OK	=  1	# The ontology was loaded successfully.
	DECIDER_LOADED_OK	=  2	# The deciders were loaded successfully.

	READY				=  100	# The formalizer is ready to be queried.


class Formalizer(Agentic):
	""" The Formalizer is the class that takes in natural language and produces structured data in the form of subgraphs.

	## Overview

	### The Formalizer has a double role:

	1. While building the evidence graph from text in corpora, providing nodes and edges for the EvidenceGraph to be merged into a
	coherent structure.
	2. While querying the evidence graph in natural language, identifying nodes and edges in the text of a query verifying matches
	between them and corresponding nodes and edges in the evidence graph.

	### Three layers, each with its own knowledge

	| Layer | What it knows | What it does |
	|---|---|---|
	| The caller (an Agent or the EvidenceGraph) | nothing of the ontology | asks in terms of the ontology: "extract the nodes of this text" |
	| The Formalizer | the ontology, but not the instances that exist | completes the question with the types, the relations and their definitions |
	| A [`Decider`][mercury.graph.evidence.Decider] | nothing | answers a self-contained [`Question`][mercury.graph.evidence.Question] with its model |

	The Formalizer translates: the caller never passes the ontology, and the Decider receives everything it needs in the question. The
	instances that exist are known by the EvidenceGraph.

	This functionality is often called (SIE) Structured Information Extracting.

	## Configuration

	The `extra_args` of a Formalizer are:

	- "description" (optional): exposed in the metadata of the Formalizer. It can be a string or a list of strings.
	- "ontology" (mandatory): the name of the [`AgenticGraph`][mercury.graph.evidence.AgenticGraph] it uses as its ontology.
	- "extract_nodes", "extract_edges" and "match_node": the name of the Decider that answers each question. A question that is
	missing or null is not offered.

	The ontology and the Deciders must also be in its "tools", so that the Endpoint provides them with `add_tool()`.

	## Piloting

	1. It finds its ontology among its tools and validates it: every type of entity and relationship has its parent defined, and every
	relationship connects the types of its parent or descendants of them. If anything fails, every problem is logged and it stops in
	the `ERR_ONTOLOGY_INIT` state.
	2. It finds the Decider of every question configured among its tools and checks that it answers that question and is ready. If
	anything fails, every problem is logged and it stops in the `ERR_DECIDER_INIT` state.

	The ontology and the Deciders must be piloted before the Formalizer.

	## Capabilities exposed by the Formalizer

	One for each question configured, named after the Formalizer (e.g., `extract_nodes_Formalizer`):

	| Question | The caller gives | The Decider receives |
	|---|---|---|
	| `extract_nodes` | `text`, optionally `types` (ids) and `context` | `text`, `ontology` (its types) and `context` |
	| `extract_edges` | `text`, `nodes`, optionally `relations` (ids) and `context` | `text`, `nodes`, `ontology` (its relations) and `context` |
	| `match_node` | `mention` (without `definition`), `node` and optionally `context` | `mention` with the `definition` of its type, `node` and `context` |

	`types` and `relations` restrict the question to some ids of the ontology; by default, all of them are used. The answers are those of
	the Decider. The arguments are validated, including the required fields of the objects they contain: if they are wrong, every problem
	is logged and the answer is None.

	## Types and concepts

	A type of the ontology (of entity or of relationship) is called a *concept* in the code of the Formalizer and a *type* in its
	capabilities.

	## Known Limitations

	The functionality is still very exploratory and minimalistic. In general, the whole system is very early-stage, released for
	developer use and experimentation. The best way of formalizing entities and relationships from text is still to be determined. It
	requires a functioning architecture to experiment, and that is what we are to-some-extent providing with this early-stage
	implementation.

	Args:
		schema (str): a schema (a unique name) to use for the Formalizer's ID.
		extra_args (dict): the configuration for the Formalizer.
		endpoint (Agentic): an optional Endpoint. It becomes part of the Formalizer's ID and is available via `self.endpoint`. If not
			provided, the Formalizer becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	QUESTION_KEYS = ['extract_nodes', 'match_node', 'extract_edges']	# The keys of the configuration, in the order of Question.

	ARGUMENT_TYPES = {'string': str, 'array': list, 'object': dict, 'number': (int, float)}	# The Python type of every JSON type.

	FUNCTIONS = {
		'extract_nodes': {
			'type': 'function',
			'function': {
				'name': 'extract_nodes_%s',
				'description': 'Identify the mentions of the types of the ontology in a text.',
				'parameters': {
					'type': 'object',
					'properties': {
						'text': {
							'type': 'string',
							'description': 'Text from which to identify nodes.'
						},
						'types': {
							'type': 'array',
							'items': {
								'type': 'string'
							},
							'description': 'Optional ids of the types of the ontology to look for (e.g., "person|teacher"). All of them by default.'
						},
						'context': CONTEXT_PARAMETER
					},
					'required': ['text']
				},
				'returns': {
					'type': 'array',
					'items': {
						'type': 'object',
						'description': 'One node per mention, with "mention" (the text as it appears), "type" and "confidence".'
					}
				}
			}
		},
		'match_node': {
			'type': 'function',
			'function': {
				'name': 'match_node_%s',
				'description': 'Decide whether a mention is a known instance (a node, as a "type|name" id).',
				'parameters': {
					'type': 'object',
					'properties': {
						'mention': {
							'type': 'object',
							'description': 'A mention: "mention" (the text as it appears), "type" (a type of the ontology) and optionally '
										   '"texts", a list of texts where it was found.',
							'required': ['mention', 'type']
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
		},
		'extract_edges': {
			'type': 'function',
			'function': {
				'name': 'extract_edges_%s',
				'description': 'Identify the edges of the relations of the ontology between the nodes of a text.',
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
						'relations': {
							'type': 'array',
							'items': {
								'type': 'string'
							},
							'description': 'Optional ids of the relations of the ontology to look for (e.g., "teaches_at"). All of them by '
										   'default.'
						},
						'context': CONTEXT_PARAMETER
					},
					'required': ['text', 'nodes']
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
	}

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(my_class = 'formalizer', schema = schema, endpoint = endpoint, logger = logger)

		if schema is None:			# This allows finding out the class name (to link tools) without actually instantiating a full object.
			return

		self.states = FormalizerState

		self.conf = extra_args
		self.name = schema

		self._ontology = None
		self._deciders = {}			# {question key: Decider} of the questions configured, once piloted.

		self._meta_ = self._meta()	# Just to make .meta reflect the initial state.


	def _run(self, request):
		""" Runs the Formalizer with the given request.

			(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""
		key = self.call.get(request['name'], None)

		if key is None:
			self.log_error('Formalizer does not have a function named "%s".' % request['name'])
			raise AgenticRunInvalidRequest

		answer = self._answer(key, request['arguments'])
		ret	   = {'finish_reason': 'stop', 'message': answer}

		return ret


	def _meta(self):
		""" Returns the metadata of the Formalizer.

			(See [`Agentic.meta()`][mercury.graph.evidence.Agentic.meta].)
		"""
		meta = {}
		meta['state'] = FormalizerState.INITIAL.value

		meta['description'] = self.conf.get('description', '')
		if type(meta['description']) is list:
			meta['description'] = '\n'.join(meta['description'])

		meta['capabilities'] = self._capabilities()

		return meta


	def _dry_run(self, request):
		""" Simulates running the Formalizer with the given request.

			(See [`Agentic.dry_run()`][mercury.graph.evidence.Agentic.dry_run].)

		## NOTE:

		The Endpoint takes care of validating the request according to the capabilities exposed by the Formalizer. It is not necessary to
		validate again here and the Endpoint does not forward the dry_run() request to the Formalizer. This method is provided as a
		requirement of the Agentic interface, but it is only used when you use Formalizers directly outside of an Endpoint.
		"""

		return {'status': 0, 'description': 'Valid request.'}


	def pilot(self, intent, just_once = False):
		""" Pilots the Formalizer to a new state based on the given intent: it loads and validates its ontology, then finds its Deciders.

		(See [`Agentic.pilot()`][mercury.graph.evidence.Agentic.pilot].)
		"""

		if self.meta['state'] < 0:
			self.log_error('Formalizer is in error state %d' % self._meta_['state'])

			return

		while self._meta_['state'] < intent:
			if self._meta_['state'] == self.states.INITIAL.value:
				self._meta_['state'] = self._pilot_ontology()

				if self._meta_['state'] < 0 or just_once:
					break

			if self._meta_['state'] == self.states.ONTOLOGY_LOADED_OK.value:
				self._meta_['state'] = self._pilot_deciders()

				if self._meta_['state'] < 0 or just_once:
					break

			if self._meta_['state'] == self.states.DECIDER_LOADED_OK.value:
				self._meta_['state'] = self.states.READY.value

				if just_once:
					break


	def extract_nodes(self, arguments):
		""" Answers `extract_nodes`: every mention of a type of the ontology in a text.

		Args:
			arguments (dict): 'text' (str) and optionally 'types' (list of ids) and 'context' (list).

		Returns:
			(list): One dictionary per mention with 'mention' (the text as it appears), 'type' and 'confidence', or None if the
				Formalizer cannot answer (see `_answer()`).
		"""

		result = self._answer('extract_nodes', arguments)

		return result


	def match_node(self, arguments):
		""" Answers `match_node`: whether a mention is a known instance.

		Args:
			arguments (dict): 'mention' ({'mention', 'type', 'texts'}), 'node' ({'id', 'description', 'names'}) and optionally
				'context' (list).

		Returns:
			(dict): 'score' (0..1) and 'same' (bool), or None if the Formalizer cannot answer (see `_answer()`).
		"""

		result = self._answer('match_node', arguments)

		return result


	def extract_edges(self, arguments):
		""" Answers `extract_edges`: every edge of a relation of the ontology between the nodes of a text.

		Args:
			arguments (dict): 'text' (str), 'nodes' (list of {'mention', 'id'}) and optionally 'relations' (list of ids) and 'context'
				(list).

		Returns:
			(list): One dictionary per edge with 'src', 'relation', 'dst' (ids) and 'confidence', or None if the Formalizer cannot
				answer (see `_answer()`).
		"""

		result = self._answer('extract_edges', arguments)

		return result


	def validate_initial_graph(self, ntx):
		""" Checks that an initial graph of instances (such as the one an EvidenceGraph starts from) matches the ontology of the
		Formalizer and describes every instance.

		The checks are:

		- Every instance is a name under a type of entity of the ontology (e.g., `person|student|Noah Kim` under `person|student`).
		- Every instance has a `description` that is not empty (e.g., "A science teacher at Riverside High School.").
		- Every edge has a `relation` that is a relationship of the ontology, and the types of the instances it connects are the `src`
		and `dst` of that relationship or descendants of them (e.g., a `person|student` can be the `src` of a relationship from
		`person`).

		Args:
			ntx (networkx.MultiDiGraph): the initial graph, with the instances as nodes and their relationships as edges. The ontology
				of the Formalizer must be loaded (it is once the Formalizer is piloted).

		Returns:
			(list): A list of strings, one for each problem found. It is empty if the initial graph is valid.
		"""

		errors	= self._validate_instances(ntx)
		errors += self._check_descriptions(ntx)

		return errors


	def close(self, endpoint_locked):
		""" Closes the Formalizer, persists it to disk and releases any resources it holds.

		(See [`Agentic.close()`][mercury.graph.evidence.Agentic.close].)
		"""

		# There is no state to persist, just freeing resources.
		self._ontology = None
		self._deciders = {}


	def _answer(self, key, arguments):
		""" Returns the answer of the Decider of a question, or None (logging why) if the Formalizer is not ready, does not answer the
		question or the arguments are not those of the question. """

		if self._meta_['state'] != self.states.READY.value:
			self.log_error('Formalizer %s is not ready for %s.' % (self.id, key))

			return None

		decider = self._deciders.get(key, None)

		if decider is None:
			self.log_error('Formalizer %s does not answer %s.' % (self.id, key))

			return None

		question, problems = self._question(key, arguments)

		for problem in problems:
			self.log_error('Invalid arguments of %s in Formalizer %s: %s' % (key, self.id, problem))

		if len(problems) > 0:
			return None

		capability = decider.meta['capabilities'][0]['function']['name']
		request	   = {'name': capability, 'arguments': question}
		response   = decider.run(request)

		return response['message']


	def _question(self, key, arguments):
		""" Returns the arguments of the Question for the Decider and the problems found: those of the arguments or, if they have none,
		those of translating them. """

		problems = self._argument_problems(key, arguments)

		if len(problems) > 0:
			return None, problems

		question, problems = self._translate(key, arguments)

		return question, problems


	def _translate(self, key, arguments):
		""" Returns the arguments of the Question for the Decider, completed with the ontology, and the problems found (an id that is
		not in the ontology). """

		if key == 'extract_nodes':
			return self._translate_extract_nodes(arguments)

		if key == 'extract_edges':
			return self._translate_extract_edges(arguments)

		return self._translate_match_node(arguments)


	def _translate_extract_nodes(self, arguments):
		""" Returns the arguments of `extract_nodes` for the Decider, with the types of the ontology asked for, and the problems found. """

		ids				   = arguments.get('types', None)
		concepts, problems = self._ontology_types(ids)

		question = {'text': arguments['text'], 'ontology': {'types': concepts}}
		self._copy_context(arguments, question)

		return question, problems


	def _translate_extract_edges(self, arguments):
		""" Returns the arguments of `extract_edges` for the Decider, with the relations of the ontology asked for, and the problems
		found. """

		ids					= arguments.get('relations', None)
		relations, problems = self._ontology_relations(ids)

		question = {'text': arguments['text'], 'nodes': arguments['nodes'], 'ontology': {'relations': relations}}
		self._copy_context(arguments, question)

		return question, problems


	def _translate_match_node(self, arguments):
		""" Returns the arguments of `match_node` for the Decider, with the definition of the type of the mention, and the problems
		found. """

		mention = dict(arguments['mention'])
		concept = mention['type']
		ntx		= self._ontology._graph.networkx

		if concept not in ntx.nodes:
			problem = 'Type "%s" of the mention is not in the ontology.' % concept

			return None, [problem]

		definition			  = ntx.nodes[concept].get('definition', None)
		mention['definition'] = self._definition_text(definition)

		question = {'mention': mention, 'node': arguments['node']}
		self._copy_context(arguments, question)

		return question, []


	def _copy_context(self, arguments, question):
		""" Copies the context of the arguments, if any, to the question. """

		if 'context' in arguments:
			question['context'] = arguments['context']


	def _ontology_types(self, ids):
		""" Returns the types of the ontology with the given ids (all of them if ids is None), as a list of {'id', 'definition'}, and a
		problem for every id that is not a type of the ontology. """

		ntx = self._ontology._graph.networkx

		if ids is None:
			ids = list(ntx.nodes)

		concepts = []
		problems = []
		for index in ids:
			if index not in ntx.nodes:
				problems.append('Type "%s" is not in the ontology.' % index)
				continue

			definition = ntx.nodes[index].get('definition', None)
			concept	   = {'id': index, 'definition': self._definition_text(definition)}
			concepts.append(concept)

		return concepts, problems


	def _ontology_relations(self, ids):
		""" Returns the relations of the ontology with the given ids (all of them if ids is None), as a list of {'id', 'src', 'dst',
		'definition'}, and a problem for every id that is not a relation of the ontology. """

		ntx		  = self._ontology._graph.networkx
		relations = {}
		for src, dst, index, definition in ntx.edges(keys = True, data = 'definition'):
			relation		 = {'id': index, 'src': src, 'dst': dst, 'definition': self._definition_text(definition)}
			relations[index] = relation

		if ids is None:
			ids = list(relations)

		result	 = []
		problems = []
		for index in ids:
			if index not in relations:
				problems.append('Relation "%s" is not in the ontology.' % index)
				continue

			result.append(relations[index])

		return result, problems


	def _definition_text(self, value):
		""" Returns a definition if it is a text, or an empty string otherwise (missing, or NaN from an empty cell of a .csv file). """

		if isinstance(value, str):
			return value

		return ''


	def _pilot_ontology(self):
		""" Finds and validates the ontology and returns the new state: ONTOLOGY_LOADED_OK or, logging every problem, ERR_ONTOLOGY_INIT. """

		ontology = self._find_ontology()

		if ontology is None:
			return self.states.ERR_ONTOLOGY_INIT.value

		errors = self._validate_ontology(ontology)

		for error in errors:
			self.log_error('Invalid ontology in Formalizer %s: %s' % (self.id, error))

		if len(errors) > 0:
			return self.states.ERR_ONTOLOGY_INIT.value

		self._ontology = ontology

		return self.states.ONTOLOGY_LOADED_OK.value


	def _find_ontology(self):
		""" Returns the AgenticGraph named by "ontology" in the configuration among the tools, or None (logging why) if it is not found. """

		name = self.conf.get('ontology', None)

		if name is None:
			self.log_error('Configuration error: "ontology" is mandatory while piloting Formalizer %s.' % self.id)

			return None

		endpoint_name = self.id.split('/')[0]
		class_name	  = AgenticGraph(schema = None, extra_args = None).id
		key			  = '%s/%s_%s' % (endpoint_name, class_name, name)

		if key not in self.tools:
			self.log_error('Tool with key "%s" not found while piloting Formalizer %s.' % (key, self.id))

			return None

		return self.tools[key]


	def _pilot_deciders(self):
		""" Finds the Deciders and returns the new state: DECIDER_LOADED_OK or, logging every problem, ERR_DECIDER_INIT. """

		keys = self._configured_questions()

		if len(keys) == 0:
			self.log_error('Formalizer %s answers no question: configure at least one of %s.' % (self.id, ', '.join(self.QUESTION_KEYS)))

			return self.states.ERR_DECIDER_INIT.value

		deciders = {}
		for key in keys:
			decider = self._find_decider(key)
			if decider is not None:
				deciders[key] = decider

		if len(deciders) < len(keys):
			return self.states.ERR_DECIDER_INIT.value

		self._deciders = deciders

		return self.states.DECIDER_LOADED_OK.value


	def _find_decider(self, key):
		""" Returns the Decider configured for a question among the tools, or None (logging why) if it is not found, it answers another
		question or it is not ready. """

		name	= self.conf[key]
		decider = self._decider_tool(name)

		if decider is None:
			self.log_error('Decider "%s" of %s not found in the tools of Formalizer %s.' % (name, key, self.id))

			return None

		expected = key.upper()
		if decider.question != expected:
			self.log_error('Decider "%s" answers %s, not %s, in Formalizer %s.' % (name, decider.question, expected, self.id))

			return None

		state = decider.meta['state']
		if state != DeciderState.READY.value:
			self.log_error('Decider "%s" of %s is not ready (state %d) in Formalizer %s.' % (name, key, state, self.id))

			return None

		return decider


	def _decider_tool(self, name):
		""" Returns the Decider with a name among the tools, or None if there is none. """

		for tool in self.tools.values():
			if isinstance(tool, Decider) and tool.name == name:
				return tool

		return None


	def _configured_questions(self):
		""" Returns the keys of the questions with a Decider (a key of the configuration that is not null), in the order of Question. """

		keys = []
		for key in self.QUESTION_KEYS:
			name = self.conf.get(key, None)
			if name is not None:
				keys.append(key)

		return keys


	def _capabilities(self):
		""" Returns the capabilities of the Formalizer: those of the questions configured, named after the Formalizer (e.g.,
		`extract_nodes_Formalizer`).

		Returns:
			(list): A list of capabilities, each represented as a dictionary with the following keys:

				- 'type': The type of capability (e.g., 'function').
				- 'function': A dictionary containing details about the function

				The value of 'function' is:

				* 'name': The name of the function.
				* 'description': A brief description of what the function does.
				* 'parameters': A dictionary with 'type', 'properties', and 'required'
				* 'returns': A dictionary with 'type' and 'items'
		"""

		self.call = {}

		capabilities = []
		for key in self._configured_questions():
			capability = deepcopy(self.FUNCTIONS[key])
			name	   = capability['function']['name'] % self.name
			capability['function']['name'] = name

			self.call[name] = key
			capabilities.append(capability)

		return capabilities


	def _argument_problems(self, key, arguments):
		""" Returns the problems of the arguments of a question: a required one is missing, one is unknown or one has another type. """

		if type(arguments) is not dict:
			return ['The arguments must be a dictionary.']

		parameters = self.FUNCTIONS[key]['function']['parameters']
		properties = parameters['properties']

		problems = []
		for name in parameters['required']:
			if name not in arguments:
				problems.append('Missing argument "%s".' % name)

		for name, value in arguments.items():
			problem = self._argument_problem(name, value, properties)
			if problem is not None:
				problems.append(problem)
				continue

			problems += self._field_problems(name, value, properties[name])

		return problems


	def _argument_problem(self, name, value, properties):
		""" Returns the problem of one argument (unknown or of another type than its property), or None if it has none. """

		parameter = properties.get(name, None)

		if parameter is None:
			return 'Unknown argument "%s".' % name

		expected = self.ARGUMENT_TYPES[parameter['type']]

		if not isinstance(value, expected):
			return 'Argument "%s" must be of type %s.' % (name, parameter['type'])

		return None


	def _field_problems(self, name, value, parameter):
		""" Returns the problems of the fields of an argument of the right type: a required field missing from an object, or from an
		object in an array (e.g., the "mention" of the argument 'mention' of `match_node`), or an item of another type. """

		if parameter['type'] == 'object':
			required = parameter.get('required', [])
			problems = self._missing_fields(name, value, required)

			return problems

		if parameter['type'] == 'array':
			problems = self._item_problems(name, value, parameter['items'])

			return problems

		return []


	def _item_problems(self, name, items, item_parameter):
		""" Returns the problems of the items of an array argument: an item of another type or an object that misses a required field. """

		expected = self.ARGUMENT_TYPES[item_parameter['type']]
		required = item_parameter.get('required', [])

		problems = []
		for position, item in enumerate(items):
			label = '%s[%d]' % (name, position)
			if not isinstance(item, expected):
				problems.append('Argument "%s" must be of type %s.' % (label, item_parameter['type']))
				continue

			problems += self._missing_fields(label, item, required)

		return problems


	def _missing_fields(self, label, value, required):
		""" Returns a problem for every required field missing from an object argument. """

		problems = []
		for field in required:
			if field not in value:
				problems.append('Argument "%s" is missing "%s".' % (label, field))

		return problems


	def _validate_ontology(self, ontology):
		""" Checks that an ontology (entities as nodes and relationships as edges between them) is coherent.

		The checks are:

		- Every entity has its parent (the id without its last `|` level) defined.
		- Every relationship has its parent defined (e.g., `works_on` for `works_on|leads`).
		- The `src` and `dst` of a relationship are those of its parent or descendants of them (e.g., `works_on|leads` can go from
		`person|student` if `works_on` goes from `person`).

		That ids are unique and that the `src` and `dst` of every relationship are entities of the ontology is already checked when it
		is loaded (see [`AgenticGraph.graph_from_files()`][mercury.graph.evidence.AgenticGraph.graph_from_files]).

		Args:
			ontology (AgenticGraph): the ontology. It must be loaded (piloted) before being validated, otherwise that is the only
				problem reported.

		Returns:
			(list): A list of strings, one for each problem found. It is empty if the ontology is valid.
		"""

		if ontology._graph is None:
			return ['Ontology "%s" is not loaded.' % ontology.name]

		ntx		  = ontology._graph.networkx
		relations = self._relation_ends(ntx)

		errors  = self._check_parents(set(ntx.nodes), 'Entity', ontology.name)
		errors += self._check_parents(set(relations), 'Relationship', ontology.name)
		errors += self._check_relation_inheritance(relations)

		return errors


	def _validate_instances(self, ntx):
		""" Returns the problems of a graph of instances that does not match the ontology: an instance that is not under a type of entity
		of the ontology, or an edge without a relationship of the ontology or between instances of other types. """

		types	  = set(self._ontology._graph.networkx.nodes)
		relations = self._relation_ends(self._ontology._graph.networkx)

		return self._check_instances(ntx, types) + self._check_instance_edges(ntx, relations)


	def _check_descriptions(self, ntx):
		""" Returns an error for every instance in ntx without a description or with an empty one. """

		errors = []
		for index, description in sorted(ntx.nodes(data = 'description')):
			if not self._is_text(description):
				errors.append('Instance "%s" has no description: the initial graph needs one for every instance.' % index)

		return errors


	def _is_text(self, value):
		""" Returns True if value is a string that is not empty or only spaces (an empty cell of a .csv file is read as NaN). """

		if not isinstance(value, str):
			return False

		return value.strip() != ''


	def _check_instances(self, ntx, types):
		""" Returns an error for every instance in ntx that is not under a type of entity in types. """

		errors = []
		for index in sorted(ntx.nodes):
			if AgenticGraph.parent_of(index) is None:
				errors.append('Instance "%s" has no type: its id must start with a type of entity of the ontology.' % index)
			elif AgenticGraph.parent_of(index) not in types:
				errors.append('Instance "%s" is of type "%s", which is not in the ontology.' % (index, AgenticGraph.parent_of(index)))

		return errors


	def _check_instance_edges(self, ntx, relations):
		""" Returns the errors of every edge in ntx, sorted by edge id. """

		errors = []
		for src, dst, key, relation in sorted(ntx.edges(keys = True, data = 'relation'), key = lambda edge: str(edge[2])):
			errors += self._check_instance_edge(src, dst, key, relation, relations)

		return errors


	def _check_instance_edge(self, src, dst, key, relation, relations):
		""" Returns the errors of one edge: a missing or unknown relation, or instances of types the relation does not connect. """

		if not isinstance(relation, str):
			return ['Edge "%s" has no relation.' % key]

		if relation not in relations:
			return ['Edge "%s" has relation "%s", which is not in the ontology.' % (key, relation)]

		errors = []
		for end, instance, expected in zip(('src', 'dst'), (src, dst), relations[relation]):
			if AgenticGraph.parent_of(instance) is not None and not AgenticGraph.descends_from(AgenticGraph.parent_of(instance), expected):
				errors.append('Edge "%s": its %s "%s" is not a "%s" as required by "%s".' % (key, end, instance, expected, relation))

		return errors


	def _relation_ends(self, ntx):
		""" Returns a dictionary of relationship id: (src, dst) of the ontology ntx. """

		return {key: (src, dst) for src, dst, key in ntx.edges(keys = True)}


	def _check_relation_inheritance(self, relations):
		""" Returns an error for every src or dst of a relationship that is not that of its parent or a descendant of it. """

		errors = []
		for index, ends in sorted(relations.items()):
			parent = AgenticGraph.parent_of(index)
			if parent in relations:
				errors += self._check_inherited_ends(index, ends, parent, relations[parent])

		return errors


	def _check_inherited_ends(self, index, ends, parent, parent_ends):
		""" Returns an error for each end of a relationship that does not descend from the same end of its parent. """

		errors = []
		for end, concept, expected in zip(('src', 'dst'), ends, parent_ends):
			if not AgenticGraph.descends_from(concept, expected):
				errors.append('Relationship "%s" has %s "%s", which is not a "%s" as required by its parent "%s".' % (index, end, concept, expected, parent))

		return errors


	def _check_parents(self, indices, kind, ontology):
		""" Returns an error for every index whose parent is not in indices. kind and ontology name them in the messages. """

		errors = []
		for index in sorted(indices):
			if AgenticGraph.parent_of(index) is not None and AgenticGraph.parent_of(index) not in indices:
				errors.append('%s "%s" has no parent "%s" in %s.' % (kind, index, AgenticGraph.parent_of(index), ontology))

		return errors
