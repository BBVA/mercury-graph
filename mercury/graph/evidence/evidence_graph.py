from mercury.graph.evidence import Agentic


class EvidenceGraph(Agentic):


	def __init__(self, schema = None, parent = None, logger = None):
		super().__init__(my_class = 'evidence_graph', schema = schema, parent = parent, logger = logger)

