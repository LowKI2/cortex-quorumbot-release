"""Ersatz für `claude` in Tests: gibt Argumente und stdin als JSON zurück."""
import json
import sys

stdin = sys.stdin.read()
if "FEHLER" in stdin:
    print(json.dumps({"is_error": True, "result": "Limit erreicht"}))
    sys.exit(1)
print(json.dumps({"result": "Hallo aus dem Abo", "is_error": False,
                  "usage": {"input_tokens": 5, "output_tokens": 7}, "args": sys.argv[1:]}))
