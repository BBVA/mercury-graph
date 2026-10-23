
from .agentic import Agentic


class Crawl():
	""" A Crawl object recurses a tree in a domain up to a limited boundary and propagates its information to a target.

	## Overview

	This is used for both large-scale processes like crawling and entire source to its vector storage or the evidence graph and
	also for Agents to query sources, ontologies and graphs.

	Typical usage includes:

	* Crawl the text of a source and index its vector representation in a vector store.
	* Crawl the text of a source and formalize it into structured knowledge.
	* Query a source, an ontology, or an evidence graph, typically using an agent.

	It builds on top of the Agentic interface and is therefore necessarily abstract, it connects one Agentic to another Agentic (possibly
	the same one) using their capabilities only. An optional serializer function can be provided to handle any necessary format conversion.

	## Crawl Process

	The crawl process includes an Agentic to be crawled and it is done by exploring a tree of unique ids. The ids of the nodes to be
	explored are stored in the attribute `_pending` as a list (by recursion level) of sets of pending ids.

	The tree exploration is breadth-first search (BFS). A full step consists of: The first id at the least deep level is used to call
	`children` its (potential) children are then added to the next level of `_pending`. An object is retrieved by calling `get_object`.
	It is sent to the target (assuming it meets the criteria defined by `accept`) and removed from the `_pending` list. The number
	of processed nodes tracked by the `_done` attribute is increased by 1.

	If you provide a serializer function, the object will be passed through it before being sent to the target, **but not** before
	checking any boundary or acceptance conditions. Those conditions should expect the format as returned by the domain object.

	When you provide conditions (via `boundary_including`, `boundary_excluding` or `accept`), all of them must be met to consider the
	object to be a match. This is typically intended to check a types of objects. More complex conditions should be handled by the
	serializer function that can also reject objects by returning `None`.

	The `run()` method can run an arbitrary number of crawl steps or until the `_pending` list is empty.

	If an error occurs during any of the calls to capabilities, it sets the `_error` attribute and halts the crawl process.

	An estimate of the crawl progress can be obtained by comparing the number of processed nodes (`_done`) with the aggregates sizes
	of all pending nodes in `_pending` which is computed at the nodes_pending attribute. This provides only the ids seen so far,
	not the total number of nodes that is unknown beforehand.

	Args:
		domain (dict): The domain to be crawled and its boundary conditions is a dictionary with the following keys:

			`agentic` (Agentic): the Agentic instance to be crawled.
			`root_id` (str): the unique id of the root node from which the crawl starts.
			`children` (str): the name of a capability in the Agentic that returns a list of child nodes for a given node id. Similar to
				"children_by_idx_xxx" capability in a Source or the equivalent NavigableTree the AgenticGraph exposes. This capability must
				accept a string argument only and return a list of string.
			`get_object` (str): the name of a capability in the Agentic that returns the content or data associated with a given node id.
				Similar to "object_by_idx_xxx" capability in a Source or the equivalent NavigableTree the AgenticGraph exposes. This
				capability must accept a string argument only and return a dictionary with a valid structure expected by the target or
				the serializer function.
			`max_depth` (int, optional): the maximum depth to which the crawl should recurse.
			`boundary_including` (dict, optional): a dictionary specifying the boundary conditions defined as key-value pairs. When a
				crawled object matches all of these conditions, it is part of the boundary. E.g., {'type': 'SourceEntity: HEADER_2'} makes
				any node with this type part of the boundary. In this case, the object is included but not further traversed.
			`boundary_excluding` (dict, optional): a dictionary that works like `boundary_including` but in this case, the object is
				neither included nor further traversed.

		target (dict): The target to which the crawled information will be sent. It is a dictionary with the following keys:

			`agentic` (Agentic): the Agentic instance that will receive the crawled information.
			`target` (str): the name of a capability in the target Agentic that will handle the crawled information. This capability must
				accept two arguments: `id` (string) and `data` (dictionary containing the crawled information).
			`accept` (dict, optional): a dictionary specifying the conditions under which the crawled object should be passed to the target.
				This is similar to `boundary_including` and `boundary_excluding`, where the keys represent the attributes to check and the
				values represent the expected values for those attributes. Typically checking desired types of nodes to be accepted.
			`serializer` (function, optional): a function that takes the crawled data and converts it into the format expected by the
				target capability. If the serializer rejects the input data, it must return `None` in which case the data will not be sent
				to the target.
	"""

	def __init__(self, domain, target):
		self._domain   = domain['agentic']
		self._pending  = [set([domain['root_id']])]
		self._children = domain['children']
		self._get_obj  = domain['get_object']

		self._max_depth = domain.get('max_depth')
		self._including = domain.get('boundary_including')
		self._excluding = domain.get('boundary_excluding')

		self._boundary = self._max_depth is not None or self._including is not None or self._excluding is not None

		self._target	 = target['agentic']
		self._put_obj	 = target['target']
		self._accept	 = target.get('accept')
		self._serializer = target.get('serializer')

		self._done  = 0
		self._error = False


	@property
	def finished(self):
		""" Indicates whether the crawl has finished, either due to an error or because there are no more pending nodes. """

		return self._error or self.nodes_pending == 0


	@property
	def nodes_done(self):
		""" Returns the number of nodes that have been processed so far. """

		return self._done


	@property
	def nodes_pending(self):
		""" Returns the number of nodes that are still pending processing. """

		return sum(len(p) for p in self._pending)


	@property
	def error(self):
		""" Returns whether an error has occurred during the crawl. """

		return self._error


	def run(self, num_steps = None):
		""" Executes the crawl for a specified number of steps.

		Args:
			num_steps (int, optional): The maximum number of steps to execute. If None, the crawl continues until finished.

		Returns:
			(bool): True if the crawl has finished, False if the crawl either encountered an error or was limited by `num_steps`.
		"""

		steps = 0

		while not self.finished:
			if not self._run_step():
				return False

			self._done += 1

			steps += 1
			if num_steps is not None and steps >= num_steps:
				return False

		return True


	def _run_step(self):
		""" Executes one crawl step: processes the first pending id of the least deep level. Does nothing after an error.

		The algorithm follows the explanation provided in the class documentation (See [`Crawl`][mercury.graph.evidence.Crawl].)

		Returns:
			(bool): True if the step was executed successfully, False if an error occurred or there were no pending nodes.
		"""

		if self._error or self.nodes_pending == 0:
			return False

		for depth in range(len(self._pending)):
			if len(self._pending[depth]) > 0:
				break

		id = self._pending[depth].pop()

		try:
			ret = self._domain._run({'name': self._get_obj, 'arguments': {'index': id}})
			if ret['finish_reason'] == 'stop':
				obj = ret['message']
			else:
				self._error = True
				return False

		except Exception:
			self._error = True
			return False

		traverse = True
		include  = True

		if self._boundary:
			if self._max_depth is not None and depth >= self._max_depth:
				traverse = False

			if self._including is not None and self._matches(obj, self._including):
				traverse = False

			if self._excluding is not None and self._matches(obj, self._excluding):
				traverse = False
				include  = False

		if self._accept is not None and not self._matches(obj, self._accept):
			include = False

		if traverse:
			try:
				ret = self._domain._run({'name': self._children, 'arguments': {'index': id}})
				if ret['finish_reason'] == 'stop':
					child_ids = ret['message']
					assert isinstance(child_ids, list)

				else:
					self._error = True
					return False

			except Exception:
				self._error = True
				return False

			i = depth + 1
			if len(self._pending) <= i:
				self._pending.append(set())

			for child_id in child_ids:
				self._pending[i].add(child_id)

		if include:
			if self._serializer is not None:
				obj = self._serializer(obj)

				if obj is None:
					return True

			try:
				ret = self._target._run({'name': self._put_obj, 'arguments': obj})
				if ret['finish_reason'].lower().startswith('err'):
					self._error = True

					return False

			except Exception:
				self._error = True

				return False

		return True


	@staticmethod
	def _matches(obj, conditions):
		""" Returns True if both objects are dictionaries and all the conditions are matched in the object.

		Args:
			obj (dict): The object to check.
			conditions (dict): The conditions defined as mandatory key-value pairs that must be present in the object.

		Returns:
			(bool): True if all conditions are matched in the object, False otherwise.
		"""

		if not isinstance(obj, dict) or not isinstance(conditions, dict):
			return False

		for key, value in conditions.items():
			if obj.get(key) != value:
				return False

		return True

