import os
import sys

sys.path.insert(0, os.environ["BRIDGE_TEST_PLUGIN_DIRECTORY"])

import bridge

bridge.ENDPOINT = os.environ["BRIDGE_TEST_ENDPOINT"]
bridge.validate_endpoint = lambda endpoint: endpoint
bridge.read_token = lambda: os.environ["BRIDGE_TEST_TOKEN"]

if __name__ == "__main__":
    sys.exit(bridge.main(sys.argv[1:]))
