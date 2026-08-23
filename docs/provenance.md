# Provenance

Source repository: HomeTutor
Source commit: `397b251effeb3d2e3b751e44026c6ec429975fb6`
Source ADR path: `docs/adr/0007-agent-coach-diploma-distribution.md`
Transformation: `public-safe derivative`

D1 exports no HomeTutor runtime code, contracts, schemas, fixtures, learner
data, provider configuration or generated runtime state. It creates only the
public foundation needed to continue the D2-D7 implementation inside this
repository.

The file-level export manifest begins in D2, when versioned public contracts
and deterministic test vectors are exported. Until then, this document records
only the source decision used to derive the public boundary documentation.

Target repository baseline before D1: `81026a20ff4425e58b48a359700ddb01c76f36f7`
