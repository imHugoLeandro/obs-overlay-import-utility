from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility.live_resize import (  # noqa: E402
    resize_active_collection,
    undo_live_resize,
)
from obs_overlay_import_utility.resizer import (  # noqa: E402
    MODE_STRETCH,
    SCOPE_COLLECTION,
)


class FakeClient:
    def __init__(self, **_kwargs: object) -> None:
        self.set_requests: list[tuple[str, dict]] = []

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def scene_collections(self) -> tuple[str, list[str]]:
        return "Live Test", ["Live Test"]

    def request(self, kind: str, data: dict | None = None) -> dict:
        if kind == "GetVideoSettings":
            return {
                "baseWidth": 100,
                "baseHeight": 100,
                "outputWidth": 100,
                "outputHeight": 100,
                "fpsNumerator": 60,
                "fpsDenominator": 1,
            }
        if kind == "GetSceneList":
            return {"scenes": [{"sceneName": "Main"}]}
        if kind == "GetGroupList":
            return {"groups": []}
        if kind == "GetSceneItemList":
            return {
                "sceneItems": [{
                    "sceneItemId": 7,
                    "sourceUuid": "source-uuid",
                    "sceneItemTransform": {
                        "positionX": 10.0,
                        "positionY": 20.0,
                        "scaleX": 1.0,
                        "scaleY": 1.0,
                        "boundsType": "OBS_BOUNDS_NONE",
                    },
                }]
            }
        self.set_requests.append((kind, data or {}))
        return {}


class LiveResizeTests(unittest.TestCase):
    def test_active_collection_resizes_through_obs_and_undoes(self) -> None:
        clients: list[FakeClient] = []

        def factory(**kwargs: object) -> FakeClient:
            client = FakeClient(**kwargs)
            clients.append(client)
            return client

        with mock.patch(
            "obs_overlay_import_utility.live_resize.ObsWebSocketClient",
            side_effect=factory,
        ):
            outcome = resize_active_collection(
                password="session-only",
                collection_name="Live Test",
                scope=SCOPE_COLLECTION,
                selected_name=None,
                selected_uuid=None,
                mode=MODE_STRETCH,
                target_width=200,
                target_height=300,
            )
            self.assertTrue(outcome.result.success, outcome.result.error)
            self.assertTrue(outcome.result.live)
            self.assertEqual(outcome.result.changed_items, 1)
            transform = clients[0].set_requests[0][1]["sceneItemTransform"]
            self.assertEqual(transform["positionX"], 20.0)
            self.assertEqual(transform["positionY"], 60.0)
            self.assertEqual(transform["scaleX"], 2.0)
            self.assertEqual(transform["scaleY"], 3.0)
            self.assertEqual(clients[0].set_requests[1][0], "SetVideoSettings")

            self.assertIsNotNone(outcome.snapshot)
            self.assertIsNone(undo_live_resize("session-only", outcome.snapshot))
            self.assertEqual(clients[1].set_requests[0][0], "SetSceneItemTransform")
            self.assertEqual(clients[1].set_requests[1][0], "SetVideoSettings")


if __name__ == "__main__":
    unittest.main()
