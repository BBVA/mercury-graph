# The parts of a Source


## Overview

This section describes how text is structured in chunks, that are SourceEntity objects, that are part of a SourceFile, that is
managed by a SourceMaker, all of which are SourceNodes that share an index tree. Everything is kept in a Source, which is an Agentic
and also has a cache and a chromadb database for the chunks. We usually use the word chunk to refer to a SourceEntity that has no children,
implying that it is a leaf in the tree: a short text, a link of the cell in a table.


## Known limitations:

For production environments, this module is not yet ready. It works well enough to be used as a PoC. Everything is built on top of OSS
components. This should be seen as a starting point that will evolve into a more robust and production-ready implementation.


::: mercury.graph.evidence.Source
::: mercury.graph.evidence.SourceNode
::: mercury.graph.evidence.SourceMaker
::: mercury.graph.evidence.SourceFile
::: mercury.graph.evidence.SourceEntity

