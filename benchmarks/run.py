import time
import random
import json
import statistics
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def generate_workload(n_orders=20000, n_customers=2000):
    W = ["espresso","coffee","tea","grinder","kettle","beans","filter","mug","scale","press"]
    rnd = random.Random(42)
    customers = [{"_id": f"c{i}", "name": f"cust{i}", "city": rnd.choice(["London","Paris","Rome"])} for i in range(n_customers)]
    orders = [{"_id": f"o{i}", "customer": f"c{rnd.randrange(n_customers)}", "items": " ".join(rnd.choices(W, k=8)), "total": round(rnd.random()*1000, 2)} for i in range(n_orders)]
    return customers, orders

def percentile(data, pct):
    s = sorted(data)
    return s[min(int(len(s) * pct / 100), len(s) - 1)]

def print_report(name, latencies_us):
    print(f"  {name}:")
    print(f"    p50:  {percentile(latencies_us, 50):.1f} us")
    print(f"    p95:  {percentile(latencies_us, 95):.1f} us")
    print(f"    p99:  {percentile(latencies_us, 99):.1f} us")
    print(f"    Mean: {statistics.mean(latencies_us):.1f} us")
    total_sec = sum(latencies_us) / 1_000_000
    throughput = len(latencies_us) / total_sec if total_sec > 0 else 0
    print(f"    Throughput: {throughput:,.0f} ops/sec")

def run_benchmarks():
    print("=" * 60)
    print("CleaveDB 3.0 Benchmark Suite")
    print("=" * 60)

    print("\n[1] Workload Generation")
    t0 = time.perf_counter()
    customers, orders = generate_workload()
    print(f"  Generated {len(customers)} customers + {len(orders)} orders in {time.perf_counter()-t0:.2f}s")

    print("\n[2] Parser Throughput")
    from cleaveql.lexer import Lexer
    from cleaveql.parser import Parser
    queries = [
        'scoop from shop/orders where total >= 100 limit 10',
        'pour into shop/orders "o999" {"total": 42}',
        'count from shop/orders where total > 50',
        'heal all', 'show buckets',
        'drain shop/orders "o1"',
        'bond cust from shop/orders.customer to shop/customers',
        'describe shop/orders',
    ]
    lats = []
    for _ in range(500):
        for q in queries:
            t = time.perf_counter_ns()
            Parser(Lexer(q).tokenize()).parse()
            lats.append((time.perf_counter_ns() - t) / 1000)
    print_report("Parse latency", lats)

    print("\n[3] JSON Serialization")
    ser = []
    for order in orders[:10000]:
        t = time.perf_counter_ns()
        json.dumps(order)
        ser.append((time.perf_counter_ns() - t) / 1000)
    print_report("JSON serialize", ser)

    print("\n[4] Query Planner")
    from cleaveql.planner import PlanEnumerator
    from cleaveql.cost_model import CostModel
    cm = CostModel()
    pe = PlanEnumerator(total_pages=5000, total_rows=200000)
    pl = []
    for _ in range(5000):
        stmts = Parser(Lexer('scoop from shop/orders where total >= 100 mentioning "espresso" limit 10').tokenize()).parse()
        t = time.perf_counter_ns()
        plans = pe.enumerate_plans(stmts[0])
        best = cm.select_best_plan(plans)
        pl.append((time.perf_counter_ns() - t) / 1000)
    print_report("Plan selection", pl)
    print(f"    Chosen plan: {best.name}")

    print("\n" + "=" * 60)
    print("Benchmark complete.")
    print("=" * 60)

if __name__ == '__main__':
    run_benchmarks()
