from mercury.graph.evidence import Decider

class XNodesGl2Decider(Decider):
	def __init__(self, schema, extra_args, endpoint=None, logger=None):
		super().__init__(schema, extra_args, endpoint=endpoint, logger=logger)

		self.question = 'EXTRACT_NODES'

		self._meta_ = self._meta()	# Must be called again after setting self.question to update the capability.
