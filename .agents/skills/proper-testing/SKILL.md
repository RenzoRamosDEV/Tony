---
name: proper-testing
description: Design, write, or review tests of any kind — unit, integration, regression, or mutation — using systematic input selection and the lightest test double that gets the job done, rather than intuition or heavyweight mocking. Apply this whenever a request calls for adding tests, improving test coverage, reviewing test quality, or choosing between fakes, stubs, mocks, spies, and containers. This file only routes to the module matching the current task and does not itself contain framework-specific syntax — always load `test-design-principles.md` for input, coverage, or test-double decisions, plus whichever testing-type or language module applies.
---

# Testing

Prefer few well-designed tests over many weak ones. Apply systematic techniques to choose inputs, not intuition. Use the lightest test double that makes the test work.

LOAD references/test-design-principles.md when choosing test inputs, coverage strategy, or test doubles. Then load the module that matches your current task:

| Task / Symptom | Load this module |
|----------------|-----------------|
| Designing test cases, choosing inputs, coverage strategy | LOAD references/test-design-principles.md |
| Writing or reviewing unit tests | LOAD references/unit-testing.md |
| Writing or reviewing integration tests | LOAD references/integration-testing.md |
| Snapshot tests, golden files, regression suites | LOAD references/regression-testing.md |
| Mutation testing, measuring test suite strength | LOAD references/mutation-testing.md |
| Writing tests in Java | LOAD references/lang-java.md |
| Writing tests in Scala | LOAD references/lang-scala.md |
| Writing tests in Python | LOAD references/lang-python.md |
| Writing tests in .NET / C# | LOAD references/lang-dotnet.md |
| Writing tests in TypeScript / JavaScript | LOAD references/lang-typescript.md |
| Writing tests in PHP | LOAD references/lang-php.md |
| Writing tests in Rust | LOAD references/lang-rust.md |

Multiple modules may apply — load all that are relevant.
