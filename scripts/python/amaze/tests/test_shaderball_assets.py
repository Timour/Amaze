"""The shader-ball scene files must travel together.

The Simple crate (shaderBallScene2_Simple.usd) REFERENCES its 41MB
sibling: the ball geometry AND the render camera live in
shaderBallScene.usd. Deleting the sibling kills every Karma thumbnail
with "no cameras found" - while the app keeps the old thumbnail and
stays quiet, so nothing looks broken until someone tries to render.

That deletion happened (2026-08-01, found in the debug log): a crate
is BINARY, so a text grep for consumers reports "referenced by
nothing" and the reference dies invisibly. This test is the grep that
works.
"""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))


class ShaderBallAssetsTest(unittest.TestCase):

    RES = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "res", "usd")

    def test_the_simple_scene_and_its_reference_exist_together(self):
        simple = os.path.join(self.RES, "shaderBallScene2_Simple.usd")
        big = os.path.join(self.RES, "shaderBallScene.usd")
        self.assertTrue(os.path.exists(simple),
                        "the Simple shader-ball crate is missing")
        self.assertTrue(
            os.path.exists(big),
            "shaderBallScene.usd is missing - the Simple crate "
            "references it for the ball and the camera, and without "
            "it every Karma thumbnail dies with 'no cameras found'")
        self.assertGreater(
            os.path.getsize(big), 40_000_000,
            "shaderBallScene.usd is truncated - the full scene is "
            "about 41.7MB")


if __name__ == "__main__":
    unittest.main()
