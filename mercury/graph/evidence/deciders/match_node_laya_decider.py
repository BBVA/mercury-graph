from mercury.graph.evidence import Decider

class MatchNodeLayaDecider(Decider):
	def __init__(self, schema, extra_args, endpoint=None, logger=None):
		super().__init__(schema, extra_args, endpoint=endpoint, logger=logger)

		self.question = 'MATCH_NODE'

		self._meta_ = self._meta()	# Must be called again after setting self.question to update the capability.


	def _dry_run(self, request):
		# This method is required by the Agentic interface.
		raise NotImplementedError('MatchNodeLayaDecider does not support dry_run().')


	def _run(self, request):
		# This method is required by the Agentic interface.
		raise NotImplementedError('MatchNodeLayaDecider does not support run().')
