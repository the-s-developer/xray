import sys
import json


if "OUTPUT" not in globals():
    OUTPUT={"error":"global variable OUTPUT is not defined"}

sys.__stdout__.write(json.dumps(OUTPUT))
sys.__stdout__.flush()
