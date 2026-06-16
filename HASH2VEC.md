# Proposal -- Hash2Vec: An alternative to SparkNode2Vec that scales better

## Core Idea

Introduce Hash2Vec as an alternative embedding backend for SparkNode2Vec to support graph workloads that exceed the practical
scalability limits of Spark MLlib Word2Vec.

This has been suggested by a user via a github issue: https://github.com/BBVA/mercury-graph/issues/41


### Why?

- Spark MLlib Word2Vec has a fundamental scalability limitation: embedding_dim × vocab_size < Int.MaxValue. In practice, scalability
issues appear much earlier due to: full vocabulary collection on the driver, large embedding matrix allocation and broadcast,
repeated synchronization across training iterations.
- For large graphs, Word2Vec becomes the bottleneck long before random-walk generation.
- Hash2Vec is implemented in GraphFrames, but the integration across technologies is challenging.

### How?

- Implementing it as an option for the current SparkNode2Vec model would possibly break compatibility, we recommend a new separate
class model.
- This is a non-trivial development project.
