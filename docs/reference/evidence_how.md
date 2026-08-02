# EvidenceGraph in Production

## Intention

In some ways, `mercury.graph.EvidenceGraph` is a PoC implementation. You can very easily test the concept and build systems that provide
evidence graph-based reasoning on a single computer, with everything persisted to your file system, graphs in RAM, and simple LLM models
that run on commodity GPUs. The architecture is easy to extend, but to achieve production-level performance, most of it would have to be re-implemented/extended/maintained in a more robust way.


## The power of OSS

Hopefully, `mercury.graph.EvidenceGraph` is being released early enough to become the core of a community effort and enough people see the
value of evidence graphs to contribute to the project. You are all more than welcome [CONTRIBUTING.md](CONTRIBUTING.md).


## Some lessons on maintaining systems that explicitly handle evidence from literature

We have also listed some recommendations in bullet-form with lessons learned from the literature about similar systems.

----

From *Atomic Task Graph: A Unified Framework for Agentic Planning and Execution* (Zhang et al., 2026):

  * Make the execution graph explicit.
  * Execute the graph directly.
  * Record execution state.
  * Repair locally instead of globally.

```bibtex
@article{zhang2026atomic,
  title={Atomic Task Graph: A Unified Framework for Agentic Planning and Execution},
  author={Zhang, Yue and Chen, Sihan and Huang, Ziwen and Cui, Hanyun and Ji, Kangye and Wang, Zhi},
  journal={arXiv preprint arXiv:2607.01942},
  year={2026}
}
```

----

From *Automatic Ontology Construction Using LLMs as an External Layer of Memory, Verification, and Planning for Hybrid Intelligent Systems* (Salovskii et al., 2026):

  * Do not graph everything. Graph the concepts, states, relations, and rules needed for important questions.
  * Never let an LLM write directly to trusted memory. Write candidate deltas, validate, then publish.
  * Preserve provenance on every fact. Source, timestamp, extraction method, confidence, and version.
  * Use graphs where structure matters. Multi-hop relationships, constraints, state transitions, consistency, and explanation.
  * Evaluate by task class, not generic answer quality. Compare text RAG and graph-assisted systems specifically on multi-hop QA, rule application, contradiction detection, temporal state, and planning.

```bibtex
@article{salovskii2026automatic,
  title={Automatic Ontology Construction Using LLMs as an External Layer of Memory, Verification, and Planning for Hybrid Intelligent Systems},
  author={Salovskii, Pavel and Gorshkova, Iuliia},
  journal={arXiv preprint arXiv:2604.20795},
  year={2026}
}
```

----

From *Evidence-in-the-Loop: Trace-Driven Optimization for Customer-Service LLM Agents* (Wu et al., 2026):

  * Keep hard controls outside the LLM.
  * Normalize evidence into an auditable contract.
  * Isolate evidence channels: Use feature flags and versioned components.
  * Do not allow online self-modification.
  * Separate optimization datasets from acceptance datasets

```bibtex
@article{wu2026evidence,
  title={Evidence-in-the-Loop: Trace-Driven Optimization for Customer-Service LLM Agents},
  author={Wu, Chunming and Qiu, Dafei and Yuan, Congde and Quan, Charles and Wu, Jun and Li, Suipeng and Wu, Mo and Xie, Gavin and Chen, Hope and Yao, Max},
  journal={arXiv preprint arXiv:2607.18039},
  year={2026}
}
```
