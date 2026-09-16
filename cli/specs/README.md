# CLI software requirements specification

This directory will contain the requirements for the agent-containers CLI,
developed from the user journey through discussion and explicit approval.
The existing implementation is a source of context, not an automatically
approved statement of required behavior.

## Document sequence

1. `user-journeys.md`: user goals, starting conditions, decisions, outcomes,
   alternative paths, and recovery journeys.
2. `interface.md`: commands, arguments, options, prompts, output, exit behavior,
   and shell interaction, derived from the agreed journeys.
3. `functional.md`: required behavior and observable acceptance criteria.
4. `non-functional.md`: quality requirements and operating constraints.
5. `security.md`: containment, trust boundaries, credentials, data exposure,
   and security-sensitive choices.
6. `test.md`: test requirements, coverage of approved requirements and user
   journeys, test environments, and acceptance criteria for verification.

Additional documents will be introduced as their scope is agreed. The entries
above identify planned documents; they do not imply approval of their contents.

## Authoring process

Discuss improvements one at a time. Record requirements in the relevant document
after the user approves them. Keep observed implementation behavior distinct
from approved requirements, and leave unresolved decisions explicitly open.

This work is specification-only. It does not include implementation changes or
test execution.
