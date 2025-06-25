import sys
import asyncio
import os
import json
import argparse

from runner import execute_python_code

def main():
    parser = argparse.ArgumentParser(description="Execute a Python code file.")
    parser.add_argument("code", help="Python code to execute.")
    parser.add_argument("--no-prints", default=True, action="store_true", help="no print output")
    parser.add_argument("--max", type=int, default=3, help="max scraping")
    parser.add_argument("--chrome-path", type=str, default=None, help="Path to chrome executable")
    parser.add_argument("--user-data-dir", type=str, default=None, help="Path to Chrome user data dir")
    args = parser.parse_args()

    result = asyncio.run(execute_python_code(args.code, no_prints=args.no_prints, max_count=args.max,chrome_path=args.chrome_path,user_data_dir=args.user_data_dir))
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
