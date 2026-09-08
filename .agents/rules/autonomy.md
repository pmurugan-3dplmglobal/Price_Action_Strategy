# Operational Protocol: Plan & Consult -> Autonomous Execution

## 1. Phase 1: Planning & Alignment Phase (Consultative)
- When a task has design ambiguity, architectural trade-offs, or requires user input:
  - Feel free to propose high-level plans, ask clarifying questions, or discuss options.
  - Keep questions targeted, high-signal, and concise.

## 2. Phase 2: Execution Phase ("Once Given the Go")
- Once the user gives the go-ahead (e.g., "go", "proceed", "implement", "continue", "fix it", "approved"):
  - **Zero-Prompt Autonomous Run**: Execute the entire implementation end-to-end without asking for permission on individual steps.
  - Automatically read files, write code, run AST checks, execute regression test suites, commit/push to git, and deploy to Cloud VMs without pausing.
  - NEVER stop mid-way to ask "May I edit this file?", "May I run the test?", or "May I push to git?".
  - Keep the user updated with clean, structured progress logs until the task is 100% complete.
