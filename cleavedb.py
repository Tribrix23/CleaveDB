import os
import sys

def main():
    try:
        import cleavedb3_storage
    except ImportError:
        print("Error: cleavedb3_storage not found.")
        print("Please run: maturin build --release && pip install target/wheels/cleavedb3*.whl")
        sys.exit(1)

    # Use a local directory for the database
    db_path = os.path.join(os.getcwd(), "cleavedb_data")
    print(f"Starting CleaveDB 3.0 Engine at: {db_path}")
    
    # Initialize the Rust engine
    engine = cleavedb3_storage.CleaveDB(db_path)
    
    # Start the CleaveQL REPL
    from cleaveql.repl import start_repl
    start_repl(engine)

if __name__ == "__main__":
    main()
