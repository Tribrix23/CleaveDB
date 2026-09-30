# Contributing to CleaveDB

Thank you for your interest in contributing to CleaveDB! 

Please note that CleaveDB operates under a **Conditional Consent License**. By submitting a pull request, issue, or contribution of any kind, you agree that your contributions become the property of the CleaveDB project and are subject to the project's licensing terms.

## How to Contribute

1. **Ask for Consent First:** If you are planning a major architectural change (such as modifying the Rust storage engine, the Go coordinator, or the C++ SIMD pipeline), please open an issue first to discuss it with the maintainers.
2. **Local Setup:** 
   - Ensure you have cargo (Rust), go (Golang), and a C++ compiler supporting AVX-512/AVX2.
   - Run the build script: python build.py
3. **Running Tests:**
   - Always run the test suites before submitting code.
   - Rust storage tests: cd storage && cargo test
   - Python Mega-Test: python benchmarks/run.py
4. **Submitting a Pull Request:**
   - Clearly describe the bug you fixed or the feature you added.
   - Include the specific CleaveQL queries that test your feature.
   - Wait for a maintainer to review.

## Code Structure

* /storage - Rust B-Tree Engine, WAL, and PyO3 bindings.
* /simd - C++ hardware acceleration for dot-products and mathematical operations.
* /coordinator - Go Scatter-Gather concurrent task manager.
* /attention - Python/ONNX implementation of the semantic search transformer.
* /cleaveql - The Python-based AST parser, lexical scanner, and AST interpreter.

Thank you for making CleaveDB faster and more secure!
