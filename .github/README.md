# Issue planning

Choose the smallest form that describes the work. All form fields are optional;
placeholders can be created now and filled out as evidence becomes available.
Blank issues remain enabled. A title is still needed to create an issue.

| Form | Use it for |
| --- | --- |
| Workflow / parent | Overall scope, a milestone, and links to focused child tasks |
| Discovery / business-rule decision | An unknown rule, source, mapping, or decision requiring evidence |
| Implementation task | One SQL, Excel/output, app, access, or integration deliverable |
| Bug / correction | An observed problem, expected behavior, and reproduction/verification |

The implementation form's category supplies context; it does not dynamically
show or hide fields. Fill in only the relevant task details. Keep proposed rules
separate from confirmed behavior, and link current workflow documentation rather
than copying a whole workflow into every task. Use synthetic examples; do not
post student records, credentials, or other sensitive information.

After creating a child, use GitHub's sub-issue controls to attach it to its
parent. A parent URL typed into a form is a reference, not a relationship.
Check project membership and status, and apply the existing area label where
appropriate. Keep completed children closed. Use Backlog while scope or evidence
is incomplete; move to Ready when the task is sufficiently defined to begin.

Split work when it can be reviewed and completed independently. An ongoing
workflow parent can stay open; use finite milestones to express what can be
finished. Discovery records the decision and its references; the relevant
workflow README states the current confirmed rule, and tests verify examples.
Staff procedures and manual fallback belong in the approved Word SOPs.

The existing template filenames `new-feature-report.yml` and
`workflow-change.yml` are retained for implementation and bug forms so links
using those filenames remain valid. Existing issues are not automatically
rewritten when a template changes. Updated forms appear on GitHub after these
files reach the default branch.
