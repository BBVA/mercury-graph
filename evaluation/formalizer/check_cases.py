""" Checks that the expected output of every case in cases.json is consistent with the ontology and the known graph of the template.

It does not run any Formalizer: it only checks the dataset itself (every mention is in its text, every id is under a type of the
ontology, known ids exist, new ids do not and every edge is valid against the ontology).

Run it from the root of the repository: python evaluation/formalizer/check_cases.py [dataset]

The dataset is cases.json unless another .json file of this directory is given.
"""

import json, os, sys
from typing import Literal, NotRequired, TypedDict

import networkx as nx

from mercury.graph.evidence import AgenticGraph
from mercury.graph.evidence.agentic_graph import graph_from_files, parent_of
from mercury.graph.evidence.formalizer import validate_instances


Status = Literal['known', 'new', 'ambiguous', 'unresolved']


class Entity(TypedDict):
	mention		  : str
	id			  : str | None
	status		  : Status
	candidates	  : NotRequired[list[str]]
	type_conflict : NotRequired[bool]


class Edge(TypedDict):
	src		 : str
	relation : str
	dst		 : str


class Output(TypedDict):
	entities : list[Entity]
	edges	 : list[Edge]


class KnownNode(TypedDict):
	id			: str
	description : str


class Case(Output):
	id				  : str
	source			  : str
	text			  : str
	notes			  : str
	extra_known_nodes : NotRequired[list[KnownNode]]
	context			  : NotRequired[str]
	with_context	  : NotRequired[Output]


class Context(TypedDict):
	ontology : list[str]
	known	 : list[str]


HERE	 = os.path.dirname(os.path.abspath(__file__))
STATUSES = ('known', 'new', 'ambiguous', 'unresolved')


def csv(path: str) -> dict:
	""" Returns a file of a configuration for a tab separated .csv file. """

	return {'type': 'csv', 'path': path}


def load_context(context: Context) -> tuple[AgenticGraph, nx.MultiDiGraph]:
	""" Returns the ready ontology and the NetworkX graph of the known instances. """

	ontology = AgenticGraph(schema = 'ontology', extra_args = {'nodes': csv(context['ontology'][0]), 'edges': csv(context['ontology'][1])})
	ontology.pilot(100)
	known = graph_from_files(csv(context['known'][0]), csv(context['known'][1])).networkx

	return ontology, known


def check_case(case: Case, ontology: AgenticGraph, known: nx.MultiDiGraph) -> list[str]:
	""" Returns the problems of one case: of its expected output and, if it has a context, of its expected output with the context. """

	errors = check_output(case, case, ontology, known)
	if ('context' in case) != ('with_context' in case):
		errors.append('"context" and "with_context" go together')

	if 'with_context' in case:
		errors += ['with context: %s' % error for error in check_output(case['with_context'], case, ontology, known)]

	return ['%s: %s' % (case['id'], error) for error in errors]


def check_output(output: Output, case: Case, ontology: AgenticGraph, known: nx.MultiDiGraph) -> list[str]:
	""" Returns the problems of one expected output (its entities and edges) of a case. """

	known_ids = set(known.nodes) | {node['id'] for node in case.get('extra_known_nodes', [])}
	types	  = set(ontology._graph.networkx.nodes)
	errors	  = []

	for entity in output['entities']:
		errors += check_entity(entity, case, known_ids, types)

	return errors + check_edges(output, case, ontology)


def check_entity(entity: Entity, case: Case, known_ids: set[str], types: set[str]) -> list[str]:
	""" Returns the problems of one expected entity. """

	errors = []
	if entity['mention'] not in case['text']:
		errors.append('mention "%s" is not in the text' % entity['mention'])

	if entity['status'] not in STATUSES:
		errors.append('unknown status "%s"' % entity['status'])

	if entity['status'] == 'ambiguous':
		return errors + check_ambiguous(entity, known_ids)

	if entity['status'] == 'unresolved':
		return errors + check_unresolved(entity)

	if parent_of(entity['id']) not in types:
		errors.append('"%s" is not under a type of entity of the ontology' % entity['id'])

	errors += check_status(entity, known_ids)

	return errors


def check_ambiguous(entity: Entity, known_ids: set[str]) -> list[str]:
	""" Returns the problems of an ambiguous entity: it has no id and at least two known candidates. """

	errors = [] if entity['id'] is None else ['an ambiguous entity has no id']
	if len(entity.get('candidates', [])) < 2 or not set(entity['candidates']) <= known_ids:
		errors.append('an ambiguous entity needs at least two known candidates')

	return errors


def check_unresolved(entity: Entity) -> list[str]:
	""" Returns the problems of an unresolved mention: it has neither an id nor candidates. """

	return [] if entity['id'] is None and 'candidates' not in entity else ['an unresolved mention has neither id nor candidates']


def check_status(entity: Entity, known_ids: set[str]) -> list[str]:
	""" Returns the problems of the status of an entity with an id: known if and only if its id is known. """

	if (entity['status'] == 'known') != (entity['id'] in known_ids):
		return ['"%s" is %s' % (entity['id'], entity['status'])]

	return []


def check_edges(output: Output, case: Case, ontology: AgenticGraph) -> list[str]:
	""" Returns the problems of the expected edges: ends that are entities of the output and valid against the ontology. """

	ends   = {e['id'] for e in output['entities'] if e['status'] in ('known', 'new')}
	errors = []
	for edge in output['edges']:
		errors += ['edge %s: "%s" is not a known or new entity of the case' % (edge['relation'], edge[end]) for end in ('src', 'dst')
				   if edge[end] not in ends]

	return errors + validate_instances(expected_graph(output, case['id']), ontology)


def expected_graph(output: Output, case_id: str) -> nx.MultiDiGraph:
	""" Returns the expected instances (known and new) and edges of an output as a NetworkX graph. """

	ntx = nx.MultiDiGraph()
	ntx.add_nodes_from(e['id'] for e in output['entities'] if e['status'] in ('known', 'new'))
	for i, edge in enumerate(output['edges']):
		ntx.add_edge(edge['src'], edge['dst'], key = '%s_%d' % (case_id, i), relation = edge['relation'])

	return ntx


def get_dataset_name() -> str:
	""" Returns the file name of the dataset: the first argument that is a .json file, or cases.json. """

	names = [arg for arg in sys.argv[1:] if arg.endswith('.json')]

	return names[0] if names else 'cases.json'


def load_dataset(name: str) -> dict:
	""" Returns the dataset (its context and its cases) of a file of this directory. """

	with open(os.path.join(HERE, name)) as f:
		dataset = json.load(f)

	return dataset


def main() -> int:
	name	= get_dataset_name()
	dataset = load_dataset(name)

	ontology, known = load_context(dataset['context'])
	errors = [error for case in dataset['cases'] for error in check_case(case, ontology, known)]

	for error in errors:
		print(error)

	print('%d cases, %d problems.' % (len(dataset['cases']), len(errors)))

	return 1 if errors else 0


if __name__ == '__main__':
	sys.exit(main())
