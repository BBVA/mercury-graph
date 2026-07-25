from mercury.graph.evidence import EvidenceGraph

class MyCustomGraph(EvidenceGraph):

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		""" This is an example, you can inherit from: Agent, Agentic, AgenticGraph, EvidenceGraph, Formalizer, Source, or any
			class in mercury.graph.evidence that inherits from Agentic.

			To build your own library, just provide the source files and place appropriate imports so that the Endpoint can do:

			from my_library import MyCustomGraph

			You must preserve the (schema, endpoint, logger, extra_args) signature in the constructor.

		"""
		super().__init__(schema = schema, extra_args = extra_args, endpoint = endpoint, logger = logger)
