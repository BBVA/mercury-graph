from mercury.graph.evidence import Agentic


class Source(Agentic):


	def __init__(self, schema = None, parent = None, logger = None):
		super().__init__(my_class = 'source', schema = schema, parent = parent, logger = logger)

