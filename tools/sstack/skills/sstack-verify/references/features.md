# Project feature index

Resolve the affected project in `tools/sstack/projects.json` and run
`python3 tools/sstack/control.py features`. The standalone registry covers SStack
itself. Register each consuming project's owned paths, offline suites, dependencies
and external acceptance recipes before dispatching work. Unknown changes block.

Reuse the project's existing README, tests and acceptance records as the feature
map. Add a recipe only when those sources cannot express the real user journey.
Record intended behavior, launch/health prerequisites, trigger, observable result,
evidence location and cleanup. Separate local tests, live record readback and
rendered UI proof. A source-only recipe is not verified behavior.

Keep environment identifiers and customer records in the owning project, not this
shared package. Use [maintenance](maintenance.md) when mappings or commands drift.
