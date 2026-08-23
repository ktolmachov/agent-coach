# Fixtures

`mock_scenarios.json` contains D4 synthetic public fixtures for deterministic
offline review.

The same fixture is mirrored into `agent_coach.data` package resources so
installed wheels can run the default mock composition without a source
checkout.

The fixture bundle declares:

- a predeclared read-only mock tool subset loaded from the frozen D2 contract
  bundle;
- controlled outcomes for success, empty result, validation failure, timeout,
  rate limit, dependency failure, security failure, oversized result, prompt
  injection and fake secret;
- expected semantic outcomes for focused adapter tests.

The fixtures are not production learner data, not HomeTutor database exports
and not durable replay state.
