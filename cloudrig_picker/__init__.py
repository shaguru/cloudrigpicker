# CloudRig Picker — a floating, mannequin-style selection picker for CloudRig rigs.
# Click the "Picker" button in the 3D View header (or Sidebar ▸ Picker) to open it.

import json

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty, StringProperty)
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import picker
from .picker import STATE, CRPICKER_OT_toggle, edit_action, ensure_custom, find_rig, FIELDS, write_button


# ---------------------------------------------------------------- data stored on the rig object

class CRP_Button(bpy.types.PropertyGroup):
    label: StringProperty(name="Label", default="Button")
    kind: EnumProperty(name="Type", items=[
        ("ROT", "Rotate", "Round button: a control you mostly rotate", "DRIVER_ROTATIONAL_DIFFERENCE", 0),
        ("MOVE", "Move", "Diamond button: a control you mostly translate", "ORIENTATION_GLOBAL", 1),
        ("SWITCH", "IK/FK Switch", "Pill that flips an IK/FK custom property", "ARROW_LEFTRIGHT", 2)])
    side: EnumProperty(name="Colour", items=[
        ("C", "Centre", "Yellow"), ("R", "Right", "Red"), ("L", "Left", "Blue"), ("X", "Extra", "Purple")])
    x: FloatProperty(name="X", min=0, max=360)
    y: FloatProperty(name="Y", min=0, max=480)
    size: FloatProperty(name="Size", default=12, min=4, max=40)
    bones: StringProperty(name="Bones", description="Comma-separated bone names this button selects")
    group: StringProperty(name="Group", description="Quick-select group: torso, head, hair, arm_r, arm_l, leg_r, leg_l, hand_r, hand_l, root, custom")
    mode: EnumProperty(name="Active In", items=[
        ("NONE", "Always", "Never dimmed"), ("FK", "FK only", "Dimmed while the switch is IK"),
        ("IK", "IK only", "Dimmed while the switch is FK")])
    switch: StringProperty(name="Switch Property", description="CloudRig custom property, e.g. ik_left_arm")


# ---------------------------------------------------------------- preferences

class CRP_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    scale: FloatProperty(name="Picker Size", default=1.0, min=0.5, max=2.5)
    opacity: FloatProperty(name="Background Opacity", default=0.88, min=0.2, max=1.0, subtype="FACTOR")
    show_mannequin: BoolProperty(name="Show Mannequin", default=True)
    show_labels: BoolProperty(name="Show Labels", default=False)
    reveal_hidden: BoolProperty(name="Reveal Hidden Controls", default=True,
                                description="Unhide a bone (and its collection) when the picker selects it")
    auto_pose: BoolProperty(name="Auto Pose Mode", default=True,
                            description="Switch the rig into Pose Mode when you click a button")
    reopen_on_load: BoolProperty(name="Re-open After Loading a File", default=True)
    facing: EnumProperty(name="Figure Faces", default="BACK", items=[
        ("BACK", "Away (R on right)", "Seen from behind: the character's right side is on your right"),
        ("FRONT", "Towards you (R on left)", "Seen from the front, like a mirror")])
    show_fk: BoolProperty(name="Show Inactive FK Buttons", default=True,
                          description="Off hides FK buttons while their limb is in IK")
    show_keys: BoolProperty(name="Highlight Keyed Controls", default=True,
                            description="Glow around buttons whose controls have a key on the current frame")
    auto_curl: BoolProperty(name="Auto Curl for Fingers", default=True,
                            description="Selecting fingers from the picker switches the pivot to Individual Origins so joints curl together")
    col_key: FloatVectorProperty(name="Keyed", subtype="COLOR_GAMMA", size=3, min=0, max=1, default=(0.30, 0.92, 0.42))
    col_right: FloatVectorProperty(name="Right (.R)", subtype="COLOR_GAMMA", size=3, min=0, max=1, default=(0.91, 0.30, 0.30))
    col_left: FloatVectorProperty(name="Left (.L)", subtype="COLOR_GAMMA", size=3, min=0, max=1, default=(0.27, 0.56, 0.96))
    col_center: FloatVectorProperty(name="Centre", subtype="COLOR_GAMMA", size=3, min=0, max=1, default=(0.98, 0.78, 0.22))
    col_extra: FloatVectorProperty(name="Extra (hair, props)", subtype="COLOR_GAMMA", size=3, min=0, max=1, default=(0.70, 0.48, 0.92))
    col_body: FloatVectorProperty(name="Mannequin", subtype="COLOR_GAMMA", size=3, min=0, max=1, default=(0.60, 0.61, 0.64))
    col_bg: FloatVectorProperty(name="Background", subtype="COLOR_GAMMA", size=3, min=0, max=1, default=(0.115, 0.12, 0.13))

    def draw(self, context):
        draw_look(self.layout, self)


def draw_look(layout, p):
    col = layout.column(align=True)
    col.prop(p, "scale", slider=True)
    col.prop(p, "opacity", slider=True)
    layout.prop(p, "facing")
    row = layout.row(align=True)
    row.prop(p, "show_mannequin", toggle=True)
    row.prop(p, "show_labels", toggle=True)
    row = layout.row(align=True)
    row.prop(p, "show_fk", toggle=True, text="Inactive FK")
    row.prop(p, "show_keys", toggle=True, text="Key Glow")
    grid = layout.grid_flow(columns=2, align=True)
    for k in ("col_right", "col_left", "col_center", "col_extra", "col_key", "col_body", "col_bg"):
        grid.prop(p, k)
    layout.prop(p, "reveal_hidden")
    layout.prop(p, "auto_pose")
    layout.prop(p, "auto_curl")
    layout.prop(p, "reopen_on_load")


# ---------------------------------------------------------------- sidebar operators

class CRPICKER_OT_edit_action(bpy.types.Operator):
    """Edit the picker layout"""
    bl_idname = "crpicker.edit_action"
    bl_label = "Picker Edit"
    bl_options = {"REGISTER", "UNDO"}
    action: StringProperty()

    @classmethod
    def description(cls, context, props):
        return {
            "add_rot": "Add a round (rotate) button that selects the selected bones",
            "add_move": "Add a diamond (move) button that selects the selected bones",
            "assign": "Replace the active button's bones with the selected bones",
            "mirror": "Duplicate the active button for the other side (.L ↔ .R)",
            "delete": "Delete the active button",
        }.get(props.action, "Edit the picker layout")

    def execute(self, context):
        rig = find_rig(context)
        msg = edit_action(context, rig, self.action)
        if msg:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class CRPICKER_OT_reset(bpy.types.Operator):
    """Throw away this rig's custom layout and go back to the built-in CloudRig human layout"""
    bl_idname = "crpicker.reset"
    bl_label = "Reset to Default Layout"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        rig = find_rig(context)
        if rig:
            rig.crp_buttons.clear()
            rig.crp_active = -1
        picker.redraw_all(context.screen)
        return {"FINISHED"}


class CRPICKER_OT_export(bpy.types.Operator, ExportHelper):
    """Save this rig's picker layout to a JSON file to share with other rigs or students"""
    bl_idname = "crpicker.export"
    bl_label = "Export Picker Layout"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        rig = find_rig(context)
        if rig is None:
            self.report({"ERROR"}, "Select a rig first")
            return {"CANCELLED"}
        data = [{f: getattr(b, f) for f in FIELDS} for b in rig.crp_buttons] or \
               [dict(b) for b in picker.default_buttons()]
        with open(self.filepath, "w", encoding="utf-8") as fh:
            json.dump({"cloudrig_picker": 1, "buttons": data}, fh, indent=1)
        self.report({"INFO"}, f"Saved {len(data)} buttons")
        return {"FINISHED"}


class CRPICKER_OT_import(bpy.types.Operator, ImportHelper):
    """Load a picker layout from a JSON file onto the active rig"""
    bl_idname = "crpicker.import"
    bl_label = "Import Picker Layout"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        rig = find_rig(context)
        if rig is None:
            self.report({"ERROR"}, "Select a rig first")
            return {"CANCELLED"}
        try:
            with open(self.filepath, encoding="utf-8") as fh:
                data = json.load(fh)["buttons"]
        except Exception as e:
            self.report({"ERROR"}, f"Could not read layout: {e}")
            return {"CANCELLED"}
        rig.crp_buttons.clear()
        for d in data:
            d = dict(d)
            if d.get("mode") == "":
                d["mode"] = "NONE"
            write_button(rig.crp_buttons.add(), d)
        rig.crp_active = -1
        picker.redraw_all(context.screen)
        self.report({"INFO"}, f"Loaded {len(data)} buttons")
        return {"FINISHED"}


# ---------------------------------------------------------------- sidebar panel

class VIEW3D_PT_crpicker(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Picker"
    bl_label = "CloudRig Picker"

    def draw(self, context):
        layout = self.layout
        open_ = STATE["show"] and picker.op_alive()
        layout.operator("crpicker.toggle", text="Hide Picker" if open_ else "Show Picker",
                        icon="HIDE_ON" if open_ else "ARMATURE_DATA", depress=open_)
        rig = find_rig(context)
        layout.label(text=f"Rig: {rig.name}" if rig else "Select an armature", icon="OUTLINER_OB_ARMATURE")
        box = layout.box()
        box.label(text="How to use", icon="INFO")
        c = box.column(align=True)
        for line in ("Click a button to select its control", "Shift-click to add or remove",
                     "Double-click: select the whole limb", "Drag empty space: box select",
                     "Round = rotate · Diamond = move", "Green glow = keyed on this frame",
                     "Key All: key every picker control", "Curl: fingers bend joint by joint",
                     "Drag the title bar to move it",
                     "Ctrl+Wheel or corner grip: resize"):
            c.label(text=line)


class VIEW3D_PT_crpicker_edit(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Picker"
    bl_label = "Customize Layout"
    bl_parent_id = "VIEW3D_PT_crpicker"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        rig = find_rig(context)
        if rig is None:
            layout.label(text="Select an armature")
            return
        custom = len(rig.crp_buttons) > 0
        layout.label(text="Custom layout saved on rig" if custom else "Using built-in CloudRig human layout",
                     icon="CHECKMARK" if custom else "PRESET")
        row = layout.row(align=True)
        row.operator("crpicker.edit_action", text="Rotate Btn", icon="ADD").action = "add_rot"
        row.operator("crpicker.edit_action", text="Move Btn", icon="ADD").action = "add_move"
        layout.label(text="New buttons use the selected bones")
        a = rig.crp_active
        if custom and 0 <= a < len(rig.crp_buttons):
            b = rig.crp_buttons[a]
            box = layout.box()
            box.label(text="Active button", icon="RADIOBUT_ON")
            box.prop(b, "label")
            box.prop(b, "kind")
            box.prop(b, "side")
            box.prop(b, "bones")
            r = box.row(align=True)
            r.prop(b, "size")
            r = box.row(align=True)
            r.prop(b, "x")
            r.prop(b, "y")
            box.prop(b, "group")
            box.prop(b, "mode")
            if b.mode != "NONE" or b.kind == "SWITCH":
                box.prop(b, "switch")
            r = box.row(align=True)
            r.operator("crpicker.edit_action", text="Assign Selected", icon="BONE_DATA").action = "assign"
            r.operator("crpicker.edit_action", text="Mirror", icon="MOD_MIRROR").action = "mirror"
            r.operator("crpicker.edit_action", text="", icon="TRASH").action = "delete"
        else:
            layout.label(text="Press Edit on the picker, then click a button", icon="INFO")
        row = layout.row(align=True)
        row.operator("crpicker.export", icon="EXPORT", text="Export")
        row.operator("crpicker.import", icon="IMPORT", text="Import")
        layout.operator("crpicker.reset", icon="LOOP_BACK")


class VIEW3D_PT_crpicker_look(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Picker"
    bl_label = "Look"
    bl_parent_id = "VIEW3D_PT_crpicker"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        draw_look(self.layout, picker.prefs())


def header_button(self, context):
    open_ = STATE["show"] and picker.op_alive()
    self.layout.operator("crpicker.toggle", text="Picker", icon="ARMATURE_DATA", depress=open_)


# ---------------------------------------------------------------- register

classes = (CRP_Button, CRP_Preferences, CRPICKER_OT_toggle, CRPICKER_OT_edit_action, CRPICKER_OT_reset,
           CRPICKER_OT_export, CRPICKER_OT_import, VIEW3D_PT_crpicker, VIEW3D_PT_crpicker_edit,
           VIEW3D_PT_crpicker_look)
_handle = None


def register():
    global _handle
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.crp_buttons = CollectionProperty(type=CRP_Button)
    bpy.types.Object.crp_active = IntProperty(default=-1)
    _handle = bpy.types.SpaceView3D.draw_handler_add(picker.draw_callback, (), "WINDOW", "POST_PIXEL")
    bpy.types.VIEW3D_HT_header.append(header_button)
    if picker.on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(picker.on_load_post)
    if picker.on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(picker.on_depsgraph)


def unregister():
    global _handle
    STATE["show"] = False
    if picker.on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(picker.on_load_post)
    if picker.on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(picker.on_depsgraph)
    bpy.types.VIEW3D_HT_header.remove(header_button)
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    del bpy.types.Object.crp_active
    del bpy.types.Object.crp_buttons
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
