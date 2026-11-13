from mercury.graph.evidence import AgenticGraph

from .gl2_decider import Gl2Decider


class XEdgesGl2Decider(Gl2Decider):
	""" A [`Decider`][mercury.graph.evidence.Decider] that answers `extract_edges` with GLiNER2 (Structure and Relation Extraction).

	## How it answers

	The model is asked for every relation of the ontology in the question as a structure (`extract_json()`) with a field for each end,
	named by its type. A relation whose ends have the same type (e.g., place to place) has two fields with the same name, so the model
	only finds that the relation is in the text, not its pairs: the model is then asked again, only for those relations, for (head,
	tail) pairs (`extract_relations()`).

	The mentions at both ends are replaced by the ids of the nodes in the question, and the edges are kept if both ends are nodes with
	an id and their types are those of the relation or descendants of them. A repeated edge keeps its highest confidence, and an edge is
	dropped when the same pair has an edge of a more specific relation (e.g., works_on when works_on|leads is found). The context is not
	used.

	It knows nothing but the question: the Formalizer gives it the relations of the ontology to look for and the nodes of the text.

	## Configuration

	The `extra_args` of [`Gl2Decider`][mercury.graph.evidence.deciders.Gl2Decider]: "description", "model" (mandatory) and the options
	of the model.

	Args:
		schema (str): a schema (a unique name) to use for the Decider's ID.
		extra_args (dict): the configuration for the Decider.
		endpoint (Agentic): an optional Endpoint. It becomes part of the Decider's ID and is available via `self.endpoint`. If not
			provided, the Decider becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	def __init__(self, schema, extra_args, endpoint=None, logger=None):
		super().__init__(schema, extra_args, endpoint=endpoint, logger=logger)

		self.question = 'EXTRACT_EDGES'

		self._meta_ = self._meta()	# Must be called again after setting self.question to update the capability.


	def _answer(self, arguments):
		""" Returns the edges of the relations of the ontology between the nodes of the text.

		Args:
			arguments (dict): The arguments of `extract_edges`: 'text', 'nodes' ({'mention', 'id'}) and 'ontology' (its 'relations'
				are used).

		Returns:
			(list): One dictionary per edge with 'src', 'relation', 'dst' (ids) and 'confidence'.
		"""

		text	  = arguments['text']
		relations = self._get_relations(arguments['ontology'])
		ids		  = self._ids_by_mention(arguments['nodes'])

		found		 = self._extract_structures(text, relations)
		triples		 = self._pair_mentions(found, relations, ids)
		same_concept = self._find_same_concept_relations(found, relations)

		if len(same_concept) > 0:
			directed = self._extract_directed_pairs(text, same_concept, relations, ids)
			triples += directed

		result = self._finish_edges(triples, relations)

		return result


	def _extract_structures(self, text, relations):
		""" Returns {relation id: matches} found by the model, every relation asked as a structure named by its definition. """

		structures	  = {}
		by_definition = {}
		for index, (src, dst, definition) in relations.items():
			structures[definition]	  = [src, dst]
			by_definition[definition] = index

		extraction = self._model.extract_json(text, structures, include_confidence = True)

		result = {}
		for definition, matches in extraction.items():
			result[by_definition[definition]] = matches

		return result


	def _extract_directed_pairs(self, text, same_concept, relations, ids):
		""" Returns (src id, relation, dst id, confidence) for every (head, tail) pair the model finds for the given relations. """

		schema = {}
		for index in same_concept:
			schema[index] = relations[index][2]

		found = self._model.extract_relations(text, schema, include_confidence = True)
		pairs = found.get('relation_extraction', {})

		triples = []
		for index, matches in pairs.items():
			for pair in matches:
				src	   = ids.get(pair['head']['text'], None)
				dst	   = ids.get(pair['tail']['text'], None)
				triple = (src, index, dst, pair['head']['confidence'])
				triples.append(triple)

		return triples


	def _get_relations(self, ontology):
		""" Returns {id: (src, dst, definition)} of the relations of the ontology. """

		relations = {}
		for relation in ontology.get('relations', []):
			definition = relation.get('definition', '')
			relations[relation['id']] = (relation['src'], relation['dst'], definition)

		return relations


	def _ids_by_mention(self, nodes):
		""" Returns {mention: id} of the nodes. """

		ids = {}
		for node in nodes:
			ids[node['mention']] = node['id']

		return ids


	def _pair_mentions(self, found, relations, ids):
		""" Returns (src id, relation, dst id, confidence) for every pair of mentions of the matches of relations with different end
		types. """

		triples = []
		for index, matches in found.items():
			src_concept, dst_concept, _ = relations[index]
			if src_concept == dst_concept:
				continue

			for match in matches:
				sources		 = match.get(src_concept, [])
				destinations = match.get(dst_concept, [])
				triples		+= self._pair_match(index, sources, destinations, ids)

		return triples


	def _pair_match(self, index, sources, destinations, ids):
		""" Returns a triple for every source and destination mention of one match, with the lowest of both confidences. """

		triples = []
		for src in sources:
			for dst in destinations:
				confidence = min(src['confidence'], dst['confidence'])
				src_id	   = ids.get(src['text'], None)
				dst_id	   = ids.get(dst['text'], None)
				triples.append((src_id, index, dst_id, confidence))

		return triples


	def _find_same_concept_relations(self, found, relations):
		""" Returns the ids of the relations with the same type at both ends that the model found mentions of. """

		result = []
		for index, matches in found.items():
			src_concept, dst_concept, _ = relations[index]
			if src_concept != dst_concept:
				continue

			if self._has_mentions(matches):
				result.append(index)

		return result


	def _has_mentions(self, matches):
		""" Returns True if any field of any match has a mention. """

		for match in matches:
			for spans in match.values():
				if len(spans) > 0:
					return True

		return False


	def _finish_edges(self, triples, relations):
		""" Returns the edges of the triples with valid ends, without repeated edges or edges of a relation more generic than another. """

		valid = []
		for triple in triples:
			if self._has_valid_ends(triple, relations):
				valid.append(triple)

		best = self._keep_highest_confidence(valid)

		result = []
		for (src, index, dst), confidence in best.items():
			if self._has_more_specific_edge(src, index, dst, best):
				continue

			edge = {'src': src, 'relation': index, 'dst': dst, 'confidence': confidence}
			result.append(edge)

		return result


	def _has_valid_ends(self, triple, relations):
		""" Returns True if both ends have an id whose type is that of the relation or a descendant of it. """

		src, index, dst, _ = triple
		src_concept, dst_concept, _ = relations[index]

		if src is None or dst is None:
			return False

		src_valid = AgenticGraph.descends_from(AgenticGraph.parent_of(src), src_concept)
		dst_valid = AgenticGraph.descends_from(AgenticGraph.parent_of(dst), dst_concept)

		return src_valid and dst_valid


	def _keep_highest_confidence(self, triples):
		""" Returns {(src, relation, dst): confidence} with the highest confidence of every repeated edge. """

		best = {}
		for src, index, dst, confidence in triples:
			edge	 = (src, index, dst)
			previous = best.get(edge, 0)
			best[edge] = max(confidence, previous)

		return best


	def _has_more_specific_edge(self, src, index, dst, edges):
		""" Returns True if the same pair has an edge of a relation that descends from index. """

		for other_src, other_index, other_dst in edges:
			same_pair = (other_src, other_dst) == (src, dst)
			if same_pair and other_index != index and AgenticGraph.descends_from(other_index, index):
				return True

		return False
