"""The shader-ball scene must COMPOSE, not merely exist.

The Karma preview scene is two files: `shaderBallScene_Simple.usd`,
which the engine loads, and `shaderBallScene.usd`, which it references
for the camera, floor and lights. The ball is Houdini's own.

Break any link and every Karma thumbnail dies with "no cameras found",
while the app keeps the old thumbnail and stays quiet - so nothing looks
broken until someone renders. A crate is BINARY, so a text grep for
consumers reports "referenced by nothing" and the reference can be
deleted invisibly, which has happened.

NEVER GUARD THIS WITH A FILE SIZE. It passed for a 41.7MB file with the
camera prim deleted, and failed for a scene that was merely smaller.
This asks what the size stood in for: does the scene COMPOSE, and does
it carry the prims the engine addresses by name?

The paths are read out of `karma_scene.py`, never repeated here.
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
