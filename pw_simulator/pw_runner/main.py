import sys
import asyncio
import os
import json
import argparse

from runner import execute_python_code

def main():
    parser = argparse.ArgumentParser(description="Execute a Python code file.")
    parser.add_argument("code_file", help="Path to the Python code file to execute.")
    parser.add_argument("--no-prints",default=True , action="store_true", help="no print output")
    parser.add_argument("--max", type=int, default=3, help="max scraping")
    args = parser.parse_args()

    if not os.path.isfile(args.code_file):
        print(f"File not found: {args.code_file}")
        sys.exit(1)

    with open(args.code_file, "r", encoding="utf-8") as f:
        code = f.read()

    result = asyncio.run(execute_python_code(code, no_prints=args.no_prints,max_count=args.max))
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
