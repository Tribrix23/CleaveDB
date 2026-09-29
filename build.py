import os
import sys
import subprocess
import platform
import shutil

def run(cmd, cwd=None, required=True):
    print(f"  > {cmd}")
    result = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        if required:
            print(f"  FAILED: {result.stderr.strip()[:300]}")
            sys.exit(1)
        else:
            print(f"  WARNING: {result.stderr.strip()[:200]}")
            return False
    return True

def check_tool(name):
    return shutil.which(name) is not None

def main():
    print("=" * 60)
    print("CleaveDB 3.0 — Master Build Script")
    print(f"Platform: {platform.system()} {platform.machine()}")
    print("=" * 60)
    is_windows = platform.system() == 'Windows'
    root = os.path.dirname(os.path.abspath(__file__))

    print("\n[1/4] C++ SIMD Layer")
    print("  Handled by Rust build.rs (cc crate compiles .cpp files)")

    print("\n[2/4] Go Coordinator")
    if check_tool('go'):
        ext = '.dll' if is_windows else '.so'
        run(f'go build -buildmode=c-shared -o libcoordinator{ext} src/main.go src/merge.go',
            cwd=os.path.join(root, 'coordinator'), required=False)
    else:
        print("  SKIPPED: Go not found on PATH (coordinator features disabled)")

    print("\n[3/4] Rust Storage Engine")
    if not check_tool('cargo'):
        print("  ERROR: cargo not found. Install Rust: https://rustup.rs")
        sys.exit(1)
    run('cargo build --release', cwd=os.path.join(root, 'storage'))

    print("\n[4/4] Python Bindings")
    if check_tool('maturin'):
        run('pip install .', cwd=os.path.join(root, 'storage'))
    else:
        print("  INFO: maturin not found, using cargo build only")
        print("  Install maturin for Python bindings: pip install maturin")

    print("\n" + "=" * 60)
    print("Build complete! CleaveDB 3.0 is ready.")
    print("Run: python -m cleaveql.repl")
    print("=" * 60)

if __name__ == '__main__':
    main()
