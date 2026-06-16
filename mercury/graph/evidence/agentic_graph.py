from mercury.graph.evidence import Agentic


class AgenticGraph(Agentic):


	def __init__(self, schema = None, parent = None, logger = None):
		super().__init__(my_class = 'agentic_graph', schema = schema, parent = parent, logger = logger)

