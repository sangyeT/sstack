# Maintain project verification

Use after affected features change, a recipe fails, or on an explicitly requested
maintenance pass. This does not install a schedule.

1. Select the affected feature files from features.md. Audit index links and recent
   source changes for missing user entry points. Do not re-audit unrelated projects.
2. Read the underlying source and applicable instructions. For a broad audit,
   authorized read-only workers can each inspect one feature and return source
   citations, likely drift and a concrete live recipe. They do not drive the same
   browser or edit product code concurrently.
3. Reconcile recipes into a small number of app states. Check prerequisites before
   driving; missing projects/credentials/permission are blockers, not successes.
4. Exercise every selected feature at least once using its actual surface. One
   coordinator owns a shared browser. After surprising behavior, recheck health or
   reset owned state before retrying. Respect Kizen write approvals; if only reads
   are authorized, record that limited coverage and leave fresh-run coverage open.
5. Wrong docs -> correct the recipe. Working product inaccessible to automation ->
   fix the verification tool. Broken product -> report a separate product issue;
   never rewrite acceptance to bless the regression. Re-drive every tool fix.
6. Confirm saved evidence survives cleanup and owned processes are gone. Report
   clean (all selected coverage proved), changed (proven recipe/tool corrections),
   or blocked (required coverage missing). Unreachable needs the attempted route
   and actual prerequisite; it does not count as a passed user journey.
7. Keep changes within verification tooling/maps. Deliver one scoped PR when
   useful corrections exist; no empty maintenance PR. Record tested head/time,
   coverage and limits. Feed repeated failures into sstack-mode references/learn.md.
