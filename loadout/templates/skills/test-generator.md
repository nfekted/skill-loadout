---
name: {{name}}
description: "Write focused automated tests for existing code. Use when the user asks for unit tests, more coverage, or a regression test for a bug."
---

# {{title}}

## When to use
Adding tests for new or existing code, or reproducing a bug with a failing test before fixing it.

## Steps
1. Find the project's test framework, naming and folder conventions and follow them.
2. List the behaviours to cover: the normal path, boundaries, invalid input and error cases.
3. Write one test per behaviour with a name that states the expectation.
4. Run the tests; make sure each new test fails when the behaviour it checks is broken.

## Rules
- Test behaviour, not implementation details.
- No network, clock or randomness without controlling it.
- Keep tests independent from each other and fast.
