import sys
import json
if "RESULT" in globals():
    sys.__stdout__.write(json.dumps(RESULT))
    sys.__stdout__.flush()
else:
    sys.__stdout__.write(json.dumps({"error": "RESULT variable not defined"}))
    sys.__stdout__.flush()
