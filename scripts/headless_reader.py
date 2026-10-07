"""One isolated browser invocation, structured output only."""
import json
import sys
from gtm.headless_reader import _read
if __name__ == '__main__':
    try:
        print(json.dumps(_read(sys.argv[1], sys.argv[2])))
    except Exception as exc:
        print(str(exc)[:300])
        sys.exit(1)
