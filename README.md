# CloudRig Picker

A floating, mannequin-style picker for selecting CloudRig controls while you animate.
Version 0.2.1. Tested in Blender 5.1 with a CloudRig "Cloud Human" rig (CloudRig 2.2.x).

Built for teaching: students click big buttons on a mannequin instead of hunting for tiny bones.
Works with [CloudRig](https://extensions.blender.org/add-ons/cloudrig/) by the Blender Studio. Requires Blender 4.2+.

## Install

1. Download `cloudrig_picker-<version>.zip` from the **Releases** page of this repository.
2. In Blender: **Edit ▸ Preferences ▸ Get Extensions ▸ ⌄ (top-right) ▸ Install from Disk…** and pick the zip.
   (You can also drag the zip onto the Blender window.)

## Use

- Click **Picker** in the 3D View header (top right), or **Sidebar (N) ▸ Picker ▸ Show Picker**.
- Select your generated rig (`RIG-…`). The picker follows the active armature.

| Do this | Result |
| --- | --- |
| Click a button | Select that control (switches to Pose Mode if needed) |
| Shift-click | Add or remove from the selection |
| Double-click | Select the whole limb / group |
| Drag on empty space | Box select |
| Click empty space | Deselect all |
| Bottom pills | All, Torso, Head, Hair · Arm, Fingers, Leg (left side on the left, right side on the right) · Root, None |
| IK / FK pill by a limb | Flip CloudRig's IK/FK switch (no snapping; use CloudRig's Snap & Bake for that) |
| **Key All** | Key every picker control (+ IK/FK switches) on the current frame |
| **FK shown / hidden** | Hide FK buttons while their limb is in IK (they come back when you switch to FK) |
| **Curl** | Pivot = Individual Origins, so every selected finger joint rotates and the fingers curl into a fist. Turns on by itself when you pick fingers and switches back afterwards |
| **Rig shown / hidden** | Hide the rig's bones in the viewport and keep selecting and animating from the picker |
| Drag the title bar | Move the picker |
| Corner grip or Ctrl+Wheel | Resize |
| – / × | Collapse / close |

**Round buttons = rotate controls. Diamond buttons with arrows = move (translate) controls.**
Red = character's right, blue = left, yellow = centre, purple = extras (hair).
The figure is seen from behind, so the character's right is on your right (Look ▸ Figure Faces to flip it).
A green glow means that control has a keyframe on the current frame.
Controls that do nothing in the current IK/FK mode are faded.
Your shortcuts (G/R/S/I, Ctrl+Z, …) keep working while the mouse is over the picker.

## Customize

- **Edit** (picker header): drag buttons to move them, mouse-wheel over a button to resize.
  The bottom row becomes tools: + Rotate, + Move (from the selected bones), Assign, Mirror (.L↔.R), Delete, Done.
- **Sidebar ▸ Picker ▸ Customize Layout**: rename a button, change its type/colour/bones, IK/FK behaviour.
- Custom layouts are saved on the rig object inside the .blend. **Export / Import** shares a layout as JSON.
- **Sidebar ▸ Picker ▸ Look** (also in the add-on preferences): size, opacity, colours, labels, mannequin.

The built-in layout uses CloudRig's Cloud Human bone names (`FK-UpperArm.L`, `IK-Hand.L`, `POLE-Arm.L`,
`TORSO-Spine`, …). Buttons whose bones don't exist on a rig are hidden, so other CloudRig humans work too;
for a different rig, press Edit and build your own layout.

## Build the zip yourself

```
cd cloudrig_picker
zip -r ../cloudrig_picker-0.2.1.zip . -x "__pycache__/*"
```

or with Blender: `blender --command extension build --source-dir cloudrig_picker`.

## License

GPL-3.0-or-later (see `LICENSE`), as required for Blender add-ons.
