# Contributing

This repository is developed one implementation slice at a time. Each slice
must keep the public demo safe to clone, inspect and run without private
infrastructure.

Before opening a change:

1. Keep the write-set limited to the current slice.
2. Do not add secrets, learner data, provider configuration or generated state.
3. Do not add HomeTutor runtime imports or a dependency on a private checkout.
4. Run targeted tests, Ruff and compile checks for the touched surface.
5. Stop after the promotion report instead of starting the next slice.

D1 accepts only foundation changes. Agent Core, contracts, fixtures, mock
adapters and the Mock Agent API belong to later slices.
