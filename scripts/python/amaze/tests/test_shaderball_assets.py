"""The shader-ball scene must COMPOSE, not merely exist.

The Karma preview scene is two files: `shaderBallScene_Simple.usd`, which
the engine loads, and `shaderBallScene.usd`, which it references for the
camera, the floor and the lights. The ball itself comes from Houdini's own
`houdini/usd/assets/shaderball/shaderball.usd`.

(The entry file was `shaderBallScene2_Simple.usd` until 2026-08-10. The 2
was upstream's, distinguishing the two scenes egMatLib shipped for its
ballmode toggle; Amaze only ever shipped one, so the digit named nothing.)

Break any part of that chain and every Karma thumbnail dies with "no cameras
found" - while the app keeps the old thumbnail and stays quiet, so nothing
looks broken until someone tries to render. That deletion happened once
already (2026-08-01, found in the debug log): a crate is BINARY, so a text
grep for consumers reports "referenced by nothing" and the reference dies
invisibly.

WHY THIS TEST NO LONGER MEASURES A FILE SIZE (2026-08-10). It used to assert
`getsize(big) > 40_000_000`, because the referenced scene was 41.7MB. That
was a proxy for "intact" and a bad one in both directions: it passed for a
41.7MB file with the camera prim deleted - the exact failure above - and it
failed for a scene that was merely smaller. Both happened. The scene is
131KB now, the same composition with a 417,286-point ball that was switched
off and replaced by Houdini's own; the picture is identical, verified by
rendering both and comparing pixels (33 of 196,608 subpixels, max channel
delta 2 of 255).

So this asks the question the size was standing in for: does the scene the
engine loads compose, and does it carry the prims the engine addresses by
name? THE PATHS ARE READ OUT OF `karma_scene.py` rather than repeated here,
so the guard cannot drift from the code it guards - a hand-kept copy of a
list is a list someone can write short.
"""

import os
import re
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))


class ShaderBallAssetsTest(unittest.TestCase):

    PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RES = os.path.join(PKG, "res", "usd")
    ENGINE = os.path.join(PKG, "preview", "karma_scene.py")

    #: The scene the engine actually loads. Every other file is reached
    #: through this one.
    ENTRY = "shaderBallScene_Simple.usd"

    def _addressed_paths(self):
        """Every /shaderBallScene prim path karma_scene.py names.

        Derived, not listed: these are the paths the scaffold sets on
        `primpath1`, `camera` and the two `geopath1` parameters, and a
        scene that does not carry one of them renders nothing while
        reporting success.
        """
        with open(self.ENGINE, encoding="utf-8") as handle:
            source = handle.read()
        found = sorted(set(re.findall(r'"(/shaderBallScene[^"]*)"', source)))
        self.assertTrue(
            found,
            "no /shaderBallScene paths found in karma_scene.py - either the "
            "engine stopped addressing the scene by prim path, or this "
            "test's search has gone stale. Do not delete the search; find "
            "out which.")
        return found

    def test_both_scene_files_are_present(self):
        entry = os.path.join(self.RES, self.ENTRY)
        self.assertTrue(
            os.path.exists(entry),
            "%s is missing - it is the scene the Karma preview engine loads"
            % self.ENTRY)
        referenced = os.path.join(self.RES, "shaderBallScene.usd")
        self.assertTrue(
            os.path.exists(referenced),
            "shaderBallScene.usd is missing - %s references it for the "
            "camera, the floor and the lights, and without it every Karma "
            "thumbnail dies with 'no cameras found'" % self.ENTRY)

    def test_the_scene_composes_with_everything_the_engine_addresses(self):
        try:
            from pxr import Usd, UsdGeom
        except ImportError:                       # pragma: no cover
            self.skipTest("pxr is not importable outside Houdini")

        stage = Usd.Stage.Open(os.path.join(self.RES, self.ENTRY))
        self.assertIsNotNone(stage, "%s would not open as a USD stage"
                             % self.ENTRY)

        for path in self._addressed_paths():
            prim = stage.GetPrimAtPath(path)
            self.assertTrue(
                prim and prim.IsActive(),
                "karma_scene.py addresses %s but the composed scene has no "
                "active prim there - the thumbnail would render empty and "
                "the app would keep the old picture without saying so"
                % path)

        camera = stage.GetPrimAtPath("/shaderBallScene/cameras/RenderCam")
        self.assertEqual(
            str(camera.GetTypeName()), "Camera",
            "the render camera is not a Camera prim - husk exits with 'no "
            "cameras found' and no EXR is written")

        points = 0
        for prim in stage.TraverseAll():
            if prim.IsA(UsdGeom.Mesh) and prim.IsActive():
                positions = UsdGeom.Mesh(prim).GetPointsAttr().Get()
                points += len(positions) if positions else 0
        self.assertGreater(
            points, 0,
            "the composed scene has no renderable geometry - the ball comes "
            "from Houdini's own shaderball asset and the floor from "
            "shaderBallScene.usd, so zero points means one of those two "
            "references stopped resolving")

    def test_the_ball_and_the_floor_both_carry_geometry(self):
        """The two halves fail independently and look the same on a tile."""
        try:
            from pxr import Usd, UsdGeom
        except ImportError:                       # pragma: no cover
            self.skipTest("pxr is not importable outside Houdini")

        stage = Usd.Stage.Open(os.path.join(self.RES, self.ENTRY))
        for label, root in (("ball", "/shaderBallScene/geo/ball"),
                            ("floor", "/shaderBallScene/geo/plane")):
            prim = stage.GetPrimAtPath(root)
            self.assertTrue(prim, "%s prim %s is missing" % (label, root))
            points = 0
            for child in Usd.PrimRange(prim):
                if child.IsA(UsdGeom.Mesh) and child.IsActive():
                    positions = UsdGeom.Mesh(child).GetPointsAttr().Get()
                    points += len(positions) if positions else 0
            self.assertGreater(
                points, 0,
                "the %s under %s has no active mesh points. A thumbnail "
                "missing only its %s still renders and still looks "
                "plausible at tile size, which is why this is checked "
                "separately." % (label, root, label))


if __name__ == "__main__":
    unittest.main()
