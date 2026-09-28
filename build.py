import os
import subprocess
import sys

def run(cmd, cwd=None):
    print(f"Running: {cmd} (in {cwd or '.'})")
    try:
        subprocess.run(cmd, cwd=cwd, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Build failed: {e}")
        sys.exit(1)

def main():
    print("CleaveDB 3.0 Master Build Script")
    
    # 1. C++ SIMD (Handled by Rust cc crate in build.rs automatically)
    print("\n--- 1. C++ SIMD ---")
    print("Handled natively by Rust build.rs")

    # 2. Go Coordinator
    print("\n--- 2. Go Coordinator ---")
    run("go build -buildmode=c-shared -o libcoordinator.so src/main.go src/merge.go", cwd="coordinator")
    
    # 3. Rust Storage Engine & PyO3 Bindings
    print("\n--- 3. Rust Storage Engine (Maturin) ---")
    run("cargo build --release", cwd="storage")
    
    print("\nBuild complete! CleaveDB 3.0 is ready.")

if __name__ == "__main__":
    main()
