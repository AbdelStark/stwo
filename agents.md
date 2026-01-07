# agents.md - Agent Operating Manual for STWO

<purpose>
This document defines how AI agents should operate within the STWO codebase.
It establishes execution loops, verification standards, and coordination patterns.
</purpose>

<roles>

## Coordinator
Responsible for task decomposition, sequencing, and verification orchestration.
- Breaks complex tasks into atomic work units
- Sequences dependencies correctly
- Ensures verification gates are passed before marking complete
- Maintains state for long-running work

## Executor
Implements changes, writes tests, and runs verifications.
- Reads targeted context before acting
- Makes minimal, focused changes
- Runs verification after each change
- Reports blockers to coordinator

## Reviewer
Validates changes meet quality bar and project standards.
- Checks code correctness and style
- Verifies tests are meaningful
- Ensures performance implications are considered
- Confirms no_std compatibility when relevant

</roles>

<default_loop>

## Standard Execution Loop

```
1. GATHER CONTEXT
   - Read CLAUDE.md for project understanding
   - Identify relevant files/modules for the task
   - Check existing tests for expected behavior
   - Do NOT read entire codebase - be surgical

2. PLAN MINIMALLY
   - Identify smallest change that achieves goal
   - List files to modify (keep it small)
   - Identify verification commands needed
   - Note any performance implications

3. EXECUTE INCREMENTALLY
   - Make one logical change at a time
   - Write/update tests alongside implementation
   - Keep commits atomic and well-described
   - Prefer editing over creating new files

4. VERIFY
   - Run: cargo test --features prover (minimum)
   - Run: ./scripts/clippy.sh
   - Run: ./scripts/rust_fmt.sh --check
   - If performance-critical: run benchmarks
   - If no_std affected: cd ensure-verifier-no_std && cargo build -r

5. PERSIST STATE
   - Update .claude/harness/progress.log with checkpoint
   - If incomplete: document next action in state.md
   - Commit verified changes

6. REPEAT OR COMPLETE
   - If task incomplete: return to step 1
   - If task complete: final verification pass
   - Report completion with verification evidence
```

</default_loop>

<long_running>

## Long-Running Task Management

### Avoiding Context Bloat
- Never load entire files unless necessary
- Use grep/search to find specific sections
- Summarize what was learned, don't repeat source
- Clear working memory between subtasks

### Checkpointing State
If task spans multiple sessions:
1. Create `.claude/harness/state.md`:
   ```markdown
   ## Current Task
   [One-line description]

   ## Completed Steps
   - [x] Step 1 with outcome
   - [x] Step 2 with outcome

   ## Next Action
   [Specific next step to take]

   ## Open Questions
   - [Any blockers or decisions needed]
   ```

2. Append to `.claude/harness/progress.log`:
   ```
   [timestamp] Completed: [what was done]
   [timestamp] Verified: [what checks passed]
   ```

### Resuming Work
1. Read `.claude/harness/state.md`
2. Run doctor/smoke check: `cargo build --features prover`
3. Pick up from "Next Action"
4. Continue execution loop

### Ending Sessions Cleanly
- Ensure repo builds: `cargo build --features prover`
- Commit any verified changes
- Update state.md with next action
- Leave no uncommitted work unless explicitly checkpointed

</long_running>

<artifacts>

## Agent-Owned Artifacts

| Path | Purpose | Update Frequency |
|------|---------|------------------|
| `.claude/harness/state.md` | Current task state | Each checkpoint |
| `.claude/harness/progress.log` | Append-only progress | Each milestone |
| `.claude/harness/backlog.md` | Pending work items | As discovered |

### Creating Harness (if needed)
```bash
mkdir -p .claude/harness
echo "# State" > .claude/harness/state.md
touch .claude/harness/progress.log
```

</artifacts>

<verification>

## Definition of Done

### Minimum (all changes):
- [ ] `cargo build --features prover` succeeds
- [ ] `cargo test --features prover` passes
- [ ] `./scripts/clippy.sh` passes
- [ ] `./scripts/rust_fmt.sh --check` passes

### For public API changes:
- [ ] `cargo doc` builds without warnings
- [ ] Examples compile if affected

### For core algorithm changes:
- [ ] Run benchmarks: `./scripts/bench.sh [relevant]`
- [ ] Compare before/after (no major regression)

### For no_std-affecting changes:
- [ ] `cd ensure-verifier-no_std && cargo build -r` succeeds

### Handling Failures
1. **Test failure**: Fix before proceeding. Never skip.
2. **Clippy warning**: Address the warning. Use allow only with justification.
3. **Format error**: Run `./scripts/rust_fmt.sh` to fix.
4. **Build failure**: Investigate root cause. Check feature flags.
5. **Benchmark regression**: Investigate. May need to reconsider approach.

### When to Add Tests
- Any new public function
- Any bug fix (regression test)
- Any non-trivial logic change
- Any edge case discovered

</verification>

<coordination>

## Multi-Agent Patterns

### Work Splitting
- Split by crate/module boundaries
- Avoid overlapping file edits
- Sequence dependent changes
- One agent per feature/bugfix

### Avoiding Merge Conflicts
- Communicate file ownership
- Use atomic commits
- Merge frequently from main
- Prefer additive changes

### Dependency Sequencing
```
1. Core type changes first
2. Then dependent module updates
3. Then test updates
4. Then documentation
```

### Escalation
Escalate to human when:
- Architectural decision required
- Breaking change to public API
- Performance regression unavoidable
- Security concern identified
- Unclear requirements

</coordination>

<skills>

## Using Skills (if available)

Skills are reusable procedures in `.claude/skills/`.

### Structure
```
.claude/skills/
└── skill-name/
    └── SKILL.md
```

### When to Use
- Check skill exists before starting common task
- Prefer skill procedure over ad-hoc approach
- Report if skill is outdated or wrong

### Adding New Skills
Only add skill if:
- Task is performed frequently (3+ times)
- Procedure is stable and verified
- Skill adds clear value

</skills>

<operations>

## Operational Context

### Branches
- `dev` - Main development branch
- Feature branches from `dev`
- PRs target `dev`

### CI Requirements
All PRs must pass:
- format
- clippy
- doc
- run-tests
- run-tests-parallel
- ensure-no-std-core
- machete (unused deps)

### Release Process
- Not agent-managed
- Version in workspace Cargo.toml
- Coordinate with maintainers

</operations>

<quality_bar>

## Quality Standards

### Good Practices
- Small, focused changes
- Tests alongside implementation
- Clear commit messages
- Run full verification before claiming done
- Benchmark performance-critical changes

### Anti-Patterns
- **Premature "done"**: Claiming complete without running checks
- **Giant PRs**: Breaking atomic changes into many files
- **Untested changes**: Shipping code without test coverage
- **Over-engineering**: Adding abstractions for single use
- **Ignoring failures**: Skipping tests or suppressing warnings
- **Context dumping**: Reading entire codebase unnecessarily

### Code Style (enforced by clippy/fmt)
- `rustfmt` with `unstable_features = true`
- No unused dependencies (machete)
- Deny warnings in release
- Prefer explicit over implicit

</quality_bar>

<domain_context>

## STWO Domain Notes

### Cryptographic Awareness
- **Correctness over speed**: Wrong proofs are useless
- **Constant-time operations**: Where security-relevant
- **Field arithmetic**: M31 is 2^31 - 1, careful with overflow
- **Test vectors**: Verify against known-good values

### Performance Awareness
- SIMD operations in hot paths
- Memory layout matters for cache
- Parallelism via Rayon where marked
- Benchmark before/after for core changes

### Mathematical Concepts
- Circle polynomials (not standard FFT)
- Coset evaluation domains
- FRI protocol for polynomial commitment
- AIR constraints (degree, composition)

</domain_context>
