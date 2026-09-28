# Design by observable usage and experiments

Use for a meaningful new interaction, data model or subsystem boundary. Small
mechanical edits do not need a design tournament. Start with research.md.

1. Work backwards from usage. Write one concrete caller example or user journey:
   input, action, expected visible result, errors, permissions and ownership.
   For a reusable library, write the shortest useful tutorial/API example first.
2. Name the data shape before implementation: entity grain, typed fields,
   relationships, state transitions, authority, retry identity and concurrency.
   Prefer Kizen native components where observed capabilities fit. Identify the
   exact unmet requirement before introducing a plugin, service or parallel store.
3. If alternatives could materially change the result, compare 2–3 bounded
   candidates. Give independent designers the same grounding brief and criteria,
   without steering them to a favored answer. Each returns usage, schemas/types,
   interface signatures, failure behavior, tradeoffs and a falsifiable claim.
   Use available host models; do not assume a particular model or cloud runtime.
4. Set the experiment and decision criteria BEFORE measuring: scenario, baseline,
   sample/order if performance matters, expected observable result, budget and
   stop condition. Build disposable minimal prototypes in isolated scratch space.
   UI alternatives must be driven and compared on screen. Platform experiments
   still need approved write scope; local mocks prove only the local boundary.
5. An independent reviewer compares artifacts and measurements, not persuasive
   prose. Select or synthesize the candidate that meets the criteria with the
   least needless complexity. A tie on a genuine product preference can go to
   the user; empirically answerable questions should be tested first.
6. Implement against the selected usage and contracts. Unexpected extra state,
   repeated workarounds or casts are a reason to revisit the design. If evidence
   invalidates the premise, discard the prototype and revise the contract rather
   than defending sunk effort. Keep useful evidence and clean only owned scratch.
7. PM turns the chosen design into small issues, each ending in concrete proof.
   Save the decision, alternatives rejected and why, experiment artifacts and
   approval boundaries in the relevant Jira issue or project design record.

Do not require a human approval between these steps unless the user's scope,
actual platform gate, or consequential missing preference requires it. If an
independent reviewer is unavailable, label that gap rather than inventing one.
