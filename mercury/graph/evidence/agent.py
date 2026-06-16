from mercury.graph.evidence import Agentic


class Agent(Agentic):


	def __init__(self, schema = None, parent = None, logger = None):
		super().__init__(my_class = 'agent', schema = schema, parent = parent, logger = logger)

