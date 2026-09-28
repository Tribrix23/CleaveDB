# CleaveDB 3.0

The polyglot, AVX-512 accelerated, non-relational database with Transformer attention layers.

## Key Features
1. **Blazing Fast B+Tree**: 16KB slotted pages, CLOCK-sweep buffer pool.
2. **SIMD Neural Engine**: Native AVX-512 Multi-head attention and matrix multiplication.
3. **Go Coordinator**: Lock-free multi-shard scatter-gather routing.
4. **CleaveQL**: A declarative, English-like query language optimized for semantic routing.

## Build
Run `python build.py` to compile the C++, Rust, and Go components.

## CleaveQL Quickstart
```cleaveql
pour into shop/orders "o1" {"total": 150, "items": "espresso"}
scoop from shop/orders where total >= 100 meaning "hot caffeinated drinks"
heal all
```
