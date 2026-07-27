import os
import unittest

os.environ.setdefault("TRELLO_KEY", "test-key")
os.environ.setdefault("TRELLO_TOKEN", "test-token")

import app


class DisabledCleanupEndpointTest(unittest.TestCase):
    def test_completed_endpoint_is_gone(self):
        response = app.app.test_client().post(
            "/api/cleanup-cierny-kamen-old-data",
            headers={"X-Cleanup-Key": app.CIERNY_KAMEN_CLEANUP_KEY},
        )
        self.assertEqual(response.status_code, 410)
        self.assertEqual(
            response.json["error"], "completed cleanup endpoint disabled"
        )


if __name__ == "__main__":
    unittest.main()
