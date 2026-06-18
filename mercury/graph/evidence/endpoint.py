from mercury.graph.evidence import Agentic


class Endpoint(Agentic):
	""" The Endpoint is the class that serves an entire Agentic tree to the outside world.

	## Overview

	For any "outside" Agentic user, an Endpoint is just another Agentic service. It is just a tree of Agentic objects.
	So an Agentic ecosystem is a giant graph made of trees that use trees that use trees, etc.

	The Agentics in the tree can use objects in other branches of the tree for efficiency. This is done using Symlinks. The Endpoint
	is the only object that owns the architecture and these Symlinks. There is only one Endpoint per tree.
	The architecture is contained in an AgenticGraph object owned by the Endpoint.

	The class exposes the Endpoint via http besides its python interface. In that case, the Endpoint is run from a cli.

	"""

	def __init__(self, schema = None, parent = None, logger = None):
		super().__init__(my_class = 'endpoint', schema = schema, parent = parent, logger = logger)
