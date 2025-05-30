# Python Script Executor

This project provides a secure way to execute user-provided Python code in an isolated environment using temporary files. It injects custom header and footer code into the user script and handles JSON output parsing. Additionally, it rewrites any usage of the `playwright` library to use a custom `patchright` module instead.

## Features

* Executes arbitrary Python code securely.
* Injects custom `header.py` and `footer.py` content.
* Replaces `playwright` references with `patchright`.
* Parses JSON output from `stdout`.
* Captures logs and handles errors gracefully.
* Supports execution timeout (default: 120 seconds).

## Installation

```bash
git clone <repository-url>
cd <repository-folder>
```

**Python version required:** Python 3.7+

## Usage

Call the function asynchronously:

```python
import asyncio

code = """
print("Hello from user code!")
"""

result = asyncio.run(execute_python_code(code))
print(result)
```

## Functions

### `replace_libname(code: str) -> str`

Replaces any usage of `playwright` with `patchright` in the provided code string.

### `read_injectable_code() -> tuple[str, str]`

Reads content from `inject/header.py` and `inject/footer.py` to be prepended/appended to the user code.

### `execute_python_code(code: str) -> dict[str, Any]`

Executes the user-provided Python code with injected header/footer. Returns output, logs, and parsed JSON if available.

## Inject Folder

The `inject` folder should contain:

```text
inject/
├── header.py
└── footer.py
```

Example:

```python
# header.py
print("Header started")

# footer.py
import json
print(json.dumps({"status": "success"}))
```

## Error Handling

* If no code is provided: `"No code provided"`
* On timeout: `"Script execution timed out"`
* If `stdout` is not valid JSON: returns raw output and logs.

## License

MIT License

