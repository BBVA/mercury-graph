import os, logging, warnings

from enum import Enum

from .agentic import Agentic, AgenticRunInvalidRequest
from .agentic_graph import AgenticGraph
from .decider import Decider


class FormalizerState(Enum):
	""" The `FormalizerState` is an enumeration that defines all possible states of a Formalizer. """

	ERR_DECIDER_INIT	= -3	# Something failed loading the decider.
	ERR_ONTOLOGY_INIT	= -2	# Something failed loading the ontology.
	ERR_MODEL_INIT		= -1	# Something failed loading the model.

	INITIAL				=  0	# The initial state of the formalizer.
	MODEL_LOADED_OK		=  1	# The model was loaded successfully.
	ONTOLOGY_LOADED_OK	=  2	# The ontology was loaded successfully.
	DECIDER_LOADED_OK	=  3	# The decider was loaded successfully.

	READY				=  100	# The formalizer is ready to be queried.


class Formalizer(Agentic):
	""" The Formalizer is the class that takes in natural language and produces structured data in the form of subgraphs.

	## Overview

	### The Formalizer has a double role:

	1. While building the evidence graph from text in corpora, providing nodes and edges for the EvidenceGraph to be merged into a
	coherent structure.
	2. While querying the evidence graph in natural language, identifying nodes and edges in the text of a query verifying matches
	between them and corresponding nodes and edges in the evidence graph.

	### The level of "intelligence" of the Formalizer

	The Formalizer "speaks" the language of EvidenceGraph, has both an Agentic interface (to be used as a tool by an Agent or just exposed
	in an Endpoint) and direct access (via the parent) to its ontology and from the EvidenceGraph. It also abstracts the functionality
	of some "smart" model that does the heavy lifting.

	It is smart enough to suggest potential nodes and edges or score how strongly the definition of one node matches another (making both
	actually the same entity), but the "intelligence" about how that becomes a final EvidenceGraph is handled by either an Agent or
	the EvidenceGraph itself.

	This functionality is often called (SIE) Structured Information Extracting.

	### How GLiNER2 fits into this workflow

	Unlike in the [`PdfToMarkdown`][mercury.graph.evidence.formats.PdfToMarkdown] conversion, where a lot of valid "turn-key" solutions
	exist, and therefore we do not favor any specific tool and provide a simple configuration mechanism to integrate any tool, we
	consider GLiNER2 as the mature, efficient, open-source, CPU-friendly solution for, at least, this early stage of this project.

	#### Possible alternatives to GLiNER2 could be

	- A completely LLM-based solution using a model that could reach similar performance without disproportionate computational cost.
	- A [SpaCy](https://spacy.io/) based solution for named entity recognition and relationship extraction.
	- Something like [NuExtract3](https://huggingface.co/numind/NuExtract3) which for the moment has high GPU requirements, but works
	directly from PDF (similar to [Unlimited-OCR](https://github.com/baidu/Unlimited-OCR) for the PDF stage).

	#### The functions used in GLiNER2 terms

	- **AutoExtractor** (Basic Entity Extraction): Is used for node identification from text. It is provided a schema (the types of
	entities of the Ontology or a selection of them), and every mention found is compared with the known instances given as candidates.
	- **AutoExtractor** (Structure Extraction): Is given an `extract_json()` format created by the Formalizer to match the definitions
	of both the relationship and its elements from the Ontology.
	- **AutoExtractor** (Relation Extraction): `extract_relations()` gives (head, tail) pairs. It is only asked for the relationships
	with the same type at both ends, whose structure cannot tell one end from the other.
	Whether a mention is a known instance is not asked to GLiNER2: it is decided by the Decider.

	## The Decider


	The Formalizer gathers the context (the mention, its type, the definitions of the ontology and the texts) and the Decider decides.

	## Types and concepts

	A type of the ontology (of entity or of relationship) is called a *concept* in the code of the Formalizer (e.g., `_choose_concept()`
	or `concept_definition`) and a *type* in what its capabilities return and in the context given to the Decider (e.g., the 'type' of
	the nodes of `hint_nodes` and the 'type_definition' of a mention). The types to look for are given in the argument 'concepts'.

	## Ontology validation

	While piloting, the Formalizer checks that its ontology is coherent using
	[`validate_ontology()`](evidence_ontologies.md#validation). If any problem is found, every problem is logged
	and the Formalizer stops in the `ERR_ONTOLOGY_INIT` state. Then it creates its Decider: if its type is unknown or `ready()` finds
	any problem, every problem is logged and the Formalizer stops in the `ERR_DECIDER_INIT` state.

	## Capabilities exposed by the Formalizer

	The Formalizer exposes three capabilities:

	1. Entity Extraction (`hint_nodes`): every mention of a type of the ontology, with the known instances it can be.
	2. Relationship Extraction (`hint_edges`): every edge of a relationship of the ontology between the nodes found in a text.
	3. Node comparison (`is_same_node`): how likely a mention is a known instance, as decided by the Decider.

	## Known Limitations

	The functionality is still very exploratory and minimalistic. Specifically, the following limitations exist:

	- The extraction threshold is that of GLiNER2 (0.5): it cannot be configured.
	- The key 'definition' is hardcoded, it should be included in the config to make it easier to find and modify.
	- Mentions are compared with known instances by the words of their names, so synonyms, abbreviations and scientific names (e.g.,
	"Cuculus canorus" for the Common Cuckoo) are not linked.
	- The only Decider is RulesDecider: it only compares names (it ignores the texts) and never chooses between several candidates.
	- Pronouns and generic mentions ("she", "the club") are not resolved.
	- The direction of the edges of a relationship with the same type at both ends depends on `extract_relations()`, which finds
	few of them.
	- link_mention() is in the Formalizer until the EvidenceGraph applies those rules itself.

	In general, the whole system is very early-stage, released for developer use and experimentation. The best way of formalizing
	entities and relationships from text is still to be determined. It requires a functioning architecture to experiment, and that
	is what we are to-some-extent providing with this early-stage implementation.

	Args:
		schema (str): a schema (a unique name) to use for the Formalizer's ID.
		extra_args (dict): the configuration for the Formalizer.
		endpoint (Agentic): an optional Endpoint. It becomes part of the Formalizer's ID and is available via `self.endpoint`. If not
			provided, the Formalizer becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(my_class = 'formalizer', schema = schema, endpoint = endpoint, logger = logger)

		if schema is None:			# This allows finding out the class name (to link tools) without actually instantiating a full object.
			return

		self.states = FormalizerState

		self.conf = extra_args
		self.name = schema

		self._ontology = None
		self._model	   = None
		self._decider  = None

		self._meta_ = self._meta()	# Just to make .meta reflect the initial state.


	def _run(self, request):
		""" Runs the Formalizer with the given request.

			(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""
		call = self.call.get(request['name'], None)

		if call is None:
			self.log_error('Formalizer does not have a function named "%s".' % request['name'])
			raise AgenticRunInvalidRequest

		ret = {'finish_reason': 'stop', 'message': call(request['arguments'])}

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
		""" Pilots the Formalizer to a new state based on the given intent.

		(See [`Agentic.pilot()`][mercury.graph.evidence.Agentic.pilot].)
		"""

		if self.meta['state'] < 0:
			self.log_error('Formalizer is in error state %d' % self._meta_['state'])

			return

		while self._meta_['state'] < intent:
			if self._meta_['state'] == self.states.INITIAL.value:
				model_config = self.conf.get('model', None)
				if model_config is None:
					self.log_error('Model configuration is missing while piloting Formalizer %s.' % self.id)

					self._meta_['state'] = self.states.ERR_MODEL_INIT.value

					break

				try:
					os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')
					os.environ.setdefault('USE_TF', '0')

					from gliner2 import AutoExtractor

				except ImportError:
					AutoExtractor = None

				library = model_config.get('library', None)
				if library != 'gliner2' or AutoExtractor is None:
					self.log_error('Missing gliner2.AutoExtractor or unsupported model library while piloting Formalizer %s.' % self.id)

					self._meta_['state'] = self.states.ERR_MODEL_INIT.value

					break

				self.AutoExtractor = AutoExtractor

				model = model_config.get('model', None)
				if model is None:
					self.log_error('Model specification is missing while piloting Formalizer %s.' % self.id)

					self._meta_['state'] = self.states.ERR_MODEL_INIT.value

					break

				map_location = model_config.get('map_location', None)
				quantize = model_config.get('quantize', None)
				compile = model_config.get('compile', None)

				args = {}
				if map_location is not None:
					args['map_location'] = map_location

				if quantize is not None:
					args['quantize'] = quantize

				if compile is not None:
					args['compile'] = compile

				try:
					previous_disable_level = logging.root.manager.disable
					logging.disable(logging.WARNING)

					with warnings.catch_warnings():
						warnings.simplefilter('ignore')

						self._model = self.AutoExtractor.from_pretrained(model, **args)

					logging.disable(previous_disable_level)

					self._meta_['state'] = self.states.MODEL_LOADED_OK.value

				except Exception as e:
					self.log_error('Failed to load model while piloting Formalizer %s: %s' % (self.id, str(e)))

					self._meta_['state'] = self.states.ERR_MODEL_INIT.value

					break

				if just_once:
					break

			if self._meta_['state'] == self.states.MODEL_LOADED_OK.value:
				self._ontology = self._find_ontology()

				if self._ontology is None:
					self._meta_['state'] = self.states.ERR_ONTOLOGY_INIT.value
					break

				errors = self._validate_ontology(self._ontology)

				if len(errors) > 0:
					self._handle_ontology_errors(errors)
					break

				self._meta_['state'] = self.states.ONTOLOGY_LOADED_OK.value

				if just_once:
					break

			if self._meta_['state'] == self.states.ONTOLOGY_LOADED_OK.value:
				self._decider = self._load_decider()

				if self._decider is None:
					self._meta_['state'] = self.states.ERR_DECIDER_INIT.value
					break

				self._meta_['state'] = self.states.DECIDER_LOADED_OK.value

				if just_once:
					break

			if self._meta_['state'] == self.states.DECIDER_LOADED_OK.value:
				self._meta_['state'] = self.states.READY.value

				if just_once:
					break


	def _create_schema(self, arguments):
		ntx = self._ontology._graph.networkx
		schema = {}
		concepts = arguments.get('concepts', None)
		if concepts is None:
			for id, _ in ntx.nodes.data('id'):
				node = dict(ntx.nodes(data = True))[id]
				schema[id] = node.get('definition', '')
		else:
			for id in concepts:
				node = dict(ntx.nodes(data = True)).get(id, {})
				schema[id] = node.get('definition', '')

		schema = self._model.create_schema().entities(schema)
		return schema


	def close(self, endpoint_locked):
		""" Closes the Formalizer, persists it to disk and releases any resources it holds.

		(See [`Agentic.close()`][mercury.graph.evidence.Agentic.close].)
		"""

		# There is no state to persist, just freeing resources.
		self._ontology = None
		self._model	   = None
		self._decider  = None


