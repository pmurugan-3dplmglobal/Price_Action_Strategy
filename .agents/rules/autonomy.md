# Zero-Prompt Autonomous Execution Directive

## Absolute Rule: No Permission Pauses

1. **Unconditional Pre-Approval**:
   - The USER has permanently granted unconditional, pre-approved authorization for all operations in this project.
   - Authorized actions include: file creation, file edits, AST parsing, test execution, regression runs, shell commands, git operations (`git add`, `git commit`, `git push`), SSH commands, and cloud VM deployments (`140.245.197.71` and `129.225.69.131`).

2. **No Permission Prompts**:
   - NEVER ask the user questions like:
     - "Should I proceed with the fix?"
     - "Do you want me to execute this plan?"
     - "May I run the test?"
     - "Can I commit this to git?"
   - Do NOT use interactive confirmation modals or question tools for routine development, bug fixing, or deployment.

3. **No Blocking Planning Mode Pauses**:
   - When creating or modifying `implementation_plan.md` or other artifacts, always set `RequestFeedback: false` unless the user explicitly requested a plan review.
   - Do NOT pause execution to wait for user approval after planning. Proceed immediately to execution, verification, and deployment in the same turn.

4. **Autonomous End-to-End Pipeline**:
   - Always execute the full lifecycle autonomously:
     1. Investigate and identify root cause.
     2. Apply code modifications across all relevant files.
     3. Verify with AST syntax checks and full regression test suite.
     4. Synchronize documentation (`ISSUE_MANAGEMENT.yaml` & `MASTER_DOCUMENTATION.yaml`).
     5. Commit to git and push to `origin/master`.
     6. Pull on Cloud VMs and restart services.
     7. Provide a concise, transparent walkthrough of completed work to the user.
