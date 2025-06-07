import sys
import json

if "RESULT" in globals():
    sys.__stdout__.write(json.dumps(RESULT, indent=2))
else:
    error_message = {
        "error": "RESULT variable is not defined globally. Please assign the result to a global variable named 'RESULT'."
    }
    sys.__stdout__.write(json.dumps(error_message, indent=2))

sys.__stdout__.flush()
