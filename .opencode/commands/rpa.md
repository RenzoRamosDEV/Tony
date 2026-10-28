---
argument-hint: <requirements_definition> <auto_mode>
arguments:
- requirements_definition
- auto_mode
description: Refines requirements with the user, creates an OpenSpec proposal, and
  implements it.
---

# Goal

**Important**: `$auto_mode` is disabled by default. If enabled or set to true, make all decisions autonomously by thinking through each option and choosing the most minimal, cost-effective, yet professional approach to accomplish the overall task.


Execute in sequence:
1. Generate a concise, kebab-case name for the new requirement (e.g., `user-authentication`) and store it as `${requirements_name}`.
2. Run `/refine-requirement ${requirements_name} $requirements_definition`.
3. Make an educated guess and evaluate complexity:
  - **If the requirement is too complex**:
    - Split the output from step 2 into smaller requirement files in the `requirements` folder, prefixing each file with a 2-digit order index (e.g., `01_${requirements_name}.md`).
    - Loop through each generated file in order: run `/new /opsx:propose @requirements/xx_${requirements_name}.md` followed by `/new /opsx:apply`. **Do not stop until all sub-requirements are finished.**
  - **If it is manageable as a single requirement**:
    - Run `/new /opsx:propose @requirements/${requirements_name}.md` and then `/new /opsx:apply`. **Do not stop until finished.**