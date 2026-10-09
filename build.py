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
    print("CleaveDB 4.0.0 — Master Build Script")
    print(f"Platform: {platform.system()} {platform.machine()}")
    print("=" * 60)
    is_windows = platform.system() == 'Windows'
    root = os.path.dirname(os.path.abspath(__file__))

    print("\n[1/4] C++ SIMD Layer")
    print("  Handled by Rust build.rs (cc crate compiles .cpp files)")

    print("\n[2/4] Go Coordinator")
    if check_tool('go'):
        ext = '.exe' if is_windows else ''
        cmd_env = 'set CGO_ENABLED=0 && ' if is_windows else 'CGO_ENABLED=0 '
        run(f'{cmd_env}go build -o ../coordinator{ext} main.go merge.go',
            cwd=os.path.join(root, 'coordinator', 'src'), required=True)
        src_bin = os.path.join(root, 'coordinator', f'coordinator{ext}')
        dst_bin = os.path.join(root, f'coordinator{ext}')
        if os.path.exists(src_bin):
            shutil.copy2(src_bin, dst_bin)
        print(f"  Built coordinator{ext} successfully.")
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
    print("Build complete! CleaveDB 4.0.0 is ready.")
    print("Run: python -m cleaveql.repl")
    print("=" * 60)

if __name__ == '__main__':
    main()
