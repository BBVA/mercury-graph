from mercury.graph.evidence import Agentic


class Endpoint(Agentic):


	def __init__(self, schema = None, parent = None, logger = None):
		super().__init__(my_class = 'endpoint', schema = schema, parent = parent, logger = logger)

