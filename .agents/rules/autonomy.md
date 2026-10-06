# Operational Protocol: Full Project Access & Autonomous Execution

## 1. Full Project & Tool Access (Zero Confirmation Overhead)
- **Full Read/Write Authorization**: Full autonomous read and write access is granted across this entire project (`Price_Action_Strategy`) and the companion tools repository.
- **Zero-Prompt Directives**: Minimize back-and-forth prompts. Execute edits, file creations, test runs, and git workflows autonomously end-to-end without pausing for step-by-step confirmation.
- **Scratch Directory Utility Reuse (`scratch/`)**:
  - Actively inspect, maintain, and reuse utility scripts, inspection harnesses, and test tools stored in `scratch/`.
  - Avoid writing redundant one-off scripts if an existing utility in `scratch/` can be reused or enhanced.
- **Dedicated Central AI Tool Creation Directory (`C:\Users\poovendan\Desktop\personal\AI\AI_tools`)**:
  - Standalone, reusable, or cross-project AI tools, analyzers, CLI utilities, and trading assistants can be created and managed under `C:\Users\poovendan\Desktop\personal\AI\AI_tools`.
  - Full read/write access is explicitly authorized with zero prompt barriers.

## 2. Phase 1: Planning & Alignment Phase (Consultative)
- When a task has design ambiguity, architectural trade-offs, or requires user input:
  - Propose high-level plans, ask clarifying questions, or discuss options.
  - Keep questions targeted, high-signal, and concise.

## 3. Phase 2: Execution Phase ("Once Given the Go")
- Once the user gives the go-ahead (e.g., "go", "proceed", "implement", "continue", "fix it", "approved"):
  - **Zero-Prompt Autonomous Run**: Execute the entire implementation end-to-end without asking for permission on individual steps.
  - Automatically read files, write code, run AST checks, execute regression test suites, commit/push to git, and deploy to Cloud VMs without pausing.
  - NEVER stop mid-way to ask "May I edit this file?", "May I run the test?", or "May I push to git?".
  - Keep the user updated with clean, structured progress logs until the task is 100% complete.
