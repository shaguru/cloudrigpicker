# The floating picker: drawing, hit testing, the modal event handler and selection logic.

import time
import traceback
from math import cos, hypot, pi, sin

import bpy

from . import draw as D
from .layout import CANVAS_W, CANVAS_H, ACTIONS, EDIT_TOOLS, default_layout, mirror_button, pill_rows

ADDON = __package__

STATE = {
    "show": False,        # picker wanted on screen
    "op": None,           # running modal operator instance
    "area_ptr": 0,        # the 3D View the picker lives in
    "pos": [64.0, 64.0],  # panel offset from the region's top-left, in pixels
    "collapsed": False,
    "edit": False,
    "rig": "",
    "hover": None,
    "drag": None,
    "status": "",
    "last_click": None,
    "pivot_auto": False,   # True while the picker switched the pivot to Individual Origins for fingers
    "pivot_prev": "MEDIAN_POINT",
}

KEY_CACHE = {"sig": None, "map": {}, "dirty": True}

_DEFAULT = None
_SWITCH_CACHE = {}
POSE_SELECT = "select" in bpy.types.PoseBone.bl_rna.properties
POSE_HIDE = "hide" in bpy.types.PoseBone.bl_rna.properties

SIDE_KEYS = {"R": "col_right", "L": "col_left", "C": "col_center", "X": "col_extra"}
KIND_WORD = {"ROT": "rotate", "MOVE": "move", "SWITCH": "IK/FK switch"}


# ---------------------------------------------------------------- helpers

def prefs():
    return bpy.context.preferences.addons[ADDON].preferences


def ui_scale():
    return bpy.context.preferences.system.ui_scale


def op_alive():
    op = STATE["op"]
    if op is None:
        return False
    try:
        op.bl_idname
        return True
    except ReferenceError:
        STATE["op"] = None
        return False


def default_buttons():
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = default_layout()
    return _DEFAULT


def view3d_areas(screen):
    return [a for a in screen.areas if a.type == "VIEW_3D"] if screen else []


def target_area(screen):
    areas = view3d_areas(screen)
    for a in areas:
        if a.as_pointer() == STATE["area_ptr"]:
            return a
    if not areas:
        return None
    best = max(areas, key=lambda a: a.width * a.height)
    STATE["area_ptr"] = best.as_pointer()
    return best


def window_region(area):
    regs = [r for r in area.regions if r.type == "WINDOW"]
    return max(regs, key=lambda r: r.width * r.height) if regs else None


def redraw_all(screen=None):
    screen = screen or bpy.context.screen
    if screen:
        for a in screen.areas:
            a.tag_redraw()


def find_rig(context):
    ob = context.active_object
    if ob and ob.type == "ARMATURE":
        STATE["rig"] = ob.name
        return ob
    if ob and ob.type == "MESH":
        for m in ob.modifiers:
            if m.type == "ARMATURE" and m.object:
                return m.object
        if ob.parent and ob.parent.type == "ARMATURE":
            return ob.parent
    rig = context.scene.objects.get(STATE["rig"]) if STATE["rig"] else None
    return rig if rig and rig.type == "ARMATURE" else None


def get_buttons(rig):
    if rig is not None and len(rig.crp_buttons):
        out = []
        for i, b in enumerate(rig.crp_buttons):
            out.append(dict(idx=i, label=b.label, kind=b.kind, side=b.side, x=b.x, y=b.y, size=b.size,
                            bones=b.bones, group=b.group, mode=b.mode if b.mode != "NONE" else "",
                            switch=b.switch))
        return out
    return [dict(b, idx=None) for b in default_buttons()]


def bone_names(b):
    return [n.strip() for n in b["bones"].split(",") if n.strip()]


def is_selected(pb):
    return pb.select if POSE_SELECT else pb.bone.select


def set_selected(pb, v):
    if POSE_SELECT:
        pb.select = v
    else:
        pb.bone.select = v


def switch_owner(rig, prop):
    key = (rig.name, prop)
    name = _SWITCH_CACHE.get(key)
    if name and name in rig.pose.bones and prop in rig.pose.bones[name]:
        return rig.pose.bones[name]
    for pb in rig.pose.bones:
        if prop in pb.keys():
            _SWITCH_CACHE[key] = pb.name
            return pb
    return None


def switch_value(rig, prop):
    if not prop:
        return None
    pb = switch_owner(rig, prop)
    if pb is None:
        return None
    try:
        return float(pb[prop])
    except Exception:
        return None


def is_dimmed(rig, b):
    if not b["mode"] or not b["switch"]:
        return False
    v = switch_value(rig, b["switch"])
    if v is None:
        return False
    return (b["mode"] == "FK" and v >= 0.5) or (b["mode"] == "IK" and v < 0.5)


def side_color(p, side):
    key = SIDE_KEYS.get(side)
    return tuple(getattr(p, key)) + (1.0,) if key else (0.55, 0.55, 0.58, 1.0)


# ---------------------------------------------------------------- frame / layout in pixels

class Frame:
    pass


def make_frame(rw, rh):
    p = prefs()
    k = p.scale * ui_scale()
    F = Frame()
    F.k = k
    F.pad = 8 * k
    F.head = 26 * k
    F.cw, F.ch = CANVAS_W * k, CANVAS_H * k
    F.pill_h, F.gap = 24 * k, 4 * k
    rows = 2 if STATE["edit"] else 4
    F.flip = p.facing == "BACK"
    F.status_h = 20 * k
    F.foot = rows * (F.pill_h + F.gap) + F.status_h + (0 if STATE["edit"] else 3 * k)
    F.w = F.cw + 2 * F.pad
    body = 0 if STATE["collapsed"] else F.ch + F.foot + F.pad
    F.h = F.head + body
    px, py = STATE["pos"]
    px = min(max(px, 80 - F.w), rw - 80)
    py = min(max(py, 0), max(0, rh - F.head))
    STATE["pos"][0], STATE["pos"][1] = px, py
    F.x = px
    F.top = rh - py
    F.y = F.top - F.h
    F.cx0 = F.x + F.pad
    F.cy0 = F.top - F.head - F.ch
    F.foot_top = F.cy0 - F.pad * 0.5
    return F


def to_px(F, x, y):
    if F.flip:
        x = CANVAS_W - x
    return F.cx0 + x * F.k, F.cy0 + y * F.k


def from_px(F, x, y):
    dx, dy = (x - F.cx0) / F.k, (y - F.cy0) / F.k
    return (CANVAS_W - dx if F.flip else dx), dy


def in_rect(x, y, r):
    return r[0] <= x <= r[0] + r[2] and r[1] <= y <= r[1] + r[3]


def build_items(F, rig, buttons):
    """Everything clickable, in hit-test priority order."""
    k = F.k
    items = []
    # header buttons (right aligned)
    bh = F.head - 8 * k
    bx = F.x + F.w - 4 * k
    for key, label, w in (("close", "×", 24), ("collapse", "+" if STATE["collapsed"] else "–", 24),
                          ("edit", "Done" if STATE["edit"] else "Edit", 46)):
        bx -= w * k + 3 * k
        items.append(dict(type="hdr", key=key, label=label, rect=(bx, F.top - F.head + 4 * k, w * k, bh)))
    if STATE["collapsed"]:
        items.append(dict(type="header", rect=(F.x, F.top - F.head, F.w, F.head)))
        return items
    items.append(dict(type="grip", rect=(F.x + F.w - 16 * k, F.y, 16 * k, 16 * k)))
    edit = STATE["edit"]
    names = rig.pose.bones if rig else {}
    # buttons: small ones last so they win overlaps when reversed below
    btn_items = []
    for b in buttons:
        bn = bone_names(b)
        exist = [n for n in bn if n in names]
        if b["kind"] == "SWITCH":
            if not edit and (rig is None or switch_value(rig, b["switch"]) is None):
                continue
        elif not exist and not edit:
            continue
        if not edit and not prefs().show_fk and b["mode"] == "FK" and rig is not None and is_dimmed(rig, b):
            continue
        cx, cy = to_px(F, b["x"], b["y"])
        r = b["size"] * k
        it = dict(type="btn", b=b, cx=cx, cy=cy, r=r, exist=exist)
        if b["kind"] == "SWITCH":
            it["rect"] = (cx - 1.6 * r, cy - 0.8 * r, 3.2 * r, 1.6 * r)
        btn_items.append(it)
    btn_items.sort(key=lambda it: it["r"])
    items += btn_items
    # footer pills / edit tools
    if edit:
        entries = [("tool", l, key, "") for l, key in EDIT_TOOLS]
        cols = 3
    else:
        entries = [("pill",) + e for row in pill_rows(F.flip) for e in row]
        entries += [("act", l, key, "") for l, key in ACTIONS]
        cols = 4
    pw = (F.cw - (cols - 1) * F.gap) / cols
    for i, (typ, label, key, side) in enumerate(entries):
        r_, c_ = divmod(i, cols)
        x = F.cx0 + c_ * (pw + F.gap)
        y = F.foot_top - (r_ + 1) * F.pill_h - r_ * F.gap
        if typ == "act":
            y -= 3 * k     # small gap above the action row
        items.append(dict(type=typ, key=key, label=label, side=side, rect=(x, y, pw, F.pill_h)))
    items.append(dict(type="canvas", rect=(F.cx0 - F.pad, F.cy0, F.w, F.ch)))
    items.append(dict(type="header", rect=(F.x, F.top - F.head, F.w, F.head)))
    items.append(dict(type="panel", rect=(F.x, F.y, F.w, F.h)))
    return items


def hit(items, x, y):
    for it in items:
        if it["type"] == "btn":
            if "rect" in it:
                if in_rect(x, y, it["rect"]):
                    return it
            elif hypot(x - it["cx"], y - it["cy"]) <= it["r"] * 1.12 + 2:
                return it
        elif in_rect(x, y, it["rect"]):
            return it
    return None


def item_key(it):
    if it is None:
        return None
    if it["type"] == "btn":
        return ("btn", it["b"]["idx"], it["b"]["label"])
    return (it["type"], it.get("key"))


# ---------------------------------------------------------------- drawing

def draw_picker(context, region):
    rig = find_rig(context)
    p = prefs()
    F = make_frame(region.width, region.height)
    buttons = get_buttons(rig)
    items = build_items(F, rig, buttons)
    k = F.k
    cv = D.Canvas()
    edit = STATE["edit"]
    hover = STATE["hover"]

    bg = tuple(p.col_bg) + (p.opacity,)
    cv.fill(D.rrect(F.x, F.y, F.w, F.h, 6 * k), bg, 0)
    cv.outline(D.rrect(F.x, F.y, F.w, F.h, 6 * k), (1, 0.55, 0.15, 0.9) if edit else (1, 1, 1, 0.12),
               1.5 if edit else 1.0, 0)
    hc = D.mix(bg, (1, 1, 1, 1), 0.07)
    cv.fill(D.rrect(F.x + 1, F.top - F.head, F.w - 2, F.head - 1, 5 * k), D.with_alpha(hc, min(1, p.opacity + 0.05)), 0)
    title = rig.name if rig else "No rig selected"
    title_max = F.w - 140 * k
    ts = 12 * k
    while len(title) > 4 and D.text_width(title, ts) > title_max:
        title = title[:-2]
    cv.text(F.x + 10 * k, F.top - F.head + 8 * k, ("✎ " if edit else "") + title, ts, (0.92, 0.92, 0.92, 1))

    for it in items:
        if it["type"] == "hdr":
            x, y, w, h = it["rect"]
            on = (it["key"] == "edit" and edit)
            base = (1, 0.55, 0.15, 0.95) if on else (1, 1, 1, 0.10 if item_key(it) != hover else 0.22)
            cv.fill(D.rrect(x, y, w, h, 4 * k), base, 1)
            cv.text(x + w / 2, y + h / 2 - 4.5 * k, it["label"], 12 * k,
                    (0.08, 0.08, 0.08, 1) if on else (0.9, 0.9, 0.9, 1), "C")

    if not STATE["collapsed"]:
        if p.show_mannequin:
            draw_mannequin(cv, F, p)
        if edit:
            for gx in range(0, int(CANVAS_W) + 1, 30):
                cv.line(to_px(F, gx, 0), to_px(F, gx, CANVAS_H), (1, 1, 1, 0.04), 1, 1)
            for gy in range(0, int(CANVAS_H) + 1, 30):
                cv.line(to_px(F, 0, gy), to_px(F, CANVAS_W, gy), (1, 1, 1, 0.04), 1, 1)
        # which side is which
        for side, x in (("L", 18), ("R", CANVAS_W - 18)):
            px_, py_ = to_px(F, x if not F.flip else CANVAS_W - x, CANVAS_H - 22)
            cv.text(px_, py_, side, 15 * k, D.with_alpha(side_color(p, side), 0.9), "C")
        cv.text(F.cx0 + F.cw / 2, F.cy0 + CANVAS_H * k - 12 * k,
                "seen from behind" if F.flip else "seen from the front", 9 * k, (1, 1, 1, 0.35), "C")
        active_idx = rig.crp_active if (rig and edit) else -1
        keyed = keyed_now(context, rig) if (rig is not None and p.show_keys) else set()
        for it in items:
            if it["type"] == "btn":
                draw_button(cv, F, p, rig, it, item_key(it) == hover, active_idx, keyed)
            elif it["type"] in ("pill", "tool", "act"):
                draw_pill(cv, F, p, it, item_key(it) == hover, context)
        # grip
        gx, gy = F.x + F.w - 4 * k, F.y + 4 * k
        for i in (1, 2, 3):
            cv.line((gx - 4 * i * k, gy), (gx, gy + 4 * i * k), (1, 1, 1, 0.3), 1.2, 3)
        # box select
        bs = STATE["drag"]
        if bs and bs.get("kind") == "box":
            x0, y0 = bs["start"]
            x1, y1 = bs["cur"]
            rect = D.rrect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0), 0)
            cv.fill(rect, (1, 1, 1, 0.06), 6, aa=False)
            cv.outline(rect, (1, 1, 1, 0.7), 1, 6)
        # status line
        cv.text(F.cx0, F.y + 7 * k, status_text(rig, items, hover), 11 * k, (0.75, 0.75, 0.75, 1))
        if rig is not None and not edit and not any(i["type"] == "btn" for i in items):
            cv.text(F.cx0 + F.cw / 2, F.cy0 + F.ch / 2, "No matching controls on this rig", 13 * k,
                    (1, 0.8, 0.5, 1), "C")
            cv.text(F.cx0 + F.cw / 2, F.cy0 + F.ch / 2 - 18 * k, "Press Edit to build your own layout", 11 * k,
                    (0.8, 0.8, 0.8, 1), "C")
    cv.flush(region.width, region.height)


def status_text(rig, items, hover):
    if STATE["status"]:
        return STATE["status"]
    if hover and hover[0] == "btn":
        for it in items:
            if it["type"] == "btn" and item_key(it) == hover:
                b = it["b"]
                if b["kind"] == "SWITCH":
                    v = switch_value(rig, b["switch"]) if rig else None
                    now = "IK" if (v or 0) >= 0.5 else "FK"
                    return f"{b['label']} · now {now} · click to switch (no snapping)"
                extra = "  ·  inactive in current IK/FK mode" if rig and is_dimmed(rig, b) else ""
                if STATE["edit"]:
                    return f"{b['label']} · drag to move · wheel to resize"
                if b["group"] in ("hand_r", "hand_l"):
                    curl = bpy.context.scene.tool_settings.transform_pivot_point == "INDIVIDUAL_ORIGINS"
                    extra += "  ·  curl on: rotate to curl" if curl else "  ·  turn on Curl to bend each joint"
                return f"{b['label']} · {KIND_WORD[b['kind']]}{extra}"
    if STATE["edit"]:
        if STATE["status"]:
            return STATE["status"]
        return "Click a button, drag to move it · Sidebar ▸ Picker for details"
    if hover and hover[0] == "act":
        return {"key_all": "Key every picker control (+ IK/FK switches) on this frame",
                "fk": "Show or hide FK buttons that are inactive (limb in IK)",
                "curl": "Individual Origins pivot: selected joints each rotate, so fingers curl",
                "rig": "Hide the rig's bones in this viewport; keep selecting from the picker"}.get(hover[1], "")
    if STATE["status"]:
        return STATE["status"]
    return "Click: select · Shift: add · Dbl-click: whole limb · Drag: box"


def draw_mannequin(cv, F, p):
    from .layout import MANNEQUIN
    body = tuple(p.col_body) + (1.0,)
    joint = D.mix(body, (0, 0, 0, 1), 0.18)
    head = D.mix(body, (1, 1, 1, 1), 0.06)
    k = F.k
    for sh in MANNEQUIN:
        kind = sh[0]
        if kind.startswith("ellipse"):
            cx, cy = to_px(F, sh[1], sh[2])
            poly = D.ellipse(cx, cy, sh[3] * k, sh[4] * k)
            col = (0, 0, 0, 0.22) if kind == "ellipsef" else head if kind == "ellipseh" else body
            cv.fill(poly, col, 1, aa=kind != "ellipsef")
        elif kind == "capsule":
            x1, y1 = to_px(F, sh[1], sh[2])
            x2, y2 = to_px(F, sh[3], sh[4])
            cv.fill(D.capsule(x1, y1, x2, y2, sh[5] * k), body, 1)
        elif kind.startswith("circle"):
            cx, cy = to_px(F, sh[1], sh[2])
            cv.fill(D.circle(cx, cy, sh[3] * k), joint if kind == "circlej" else body, 2)


def glyph_color(c):
    lum = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    return (0.08, 0.08, 0.08, 0.85) if lum > 0.55 else (1, 1, 1, 0.9)


def draw_button(cv, F, p, rig, it, hovered, active_idx, keyed=frozenset()):
    b = it["b"]
    k = F.k
    cx, cy, r = it["cx"], it["cy"], it["r"]
    base = side_color(p, b["side"])
    dim = rig is not None and is_dimmed(rig, b)
    missing = not it["exist"] and b["kind"] != "SWITCH"
    alpha = 0.28 if (dim or missing) else 1.0
    col = D.mix(base, (1, 1, 1, 1), 0.28) if hovered else base
    col = D.with_alpha(col, alpha)
    gcol = glyph_color(base)

    if b["kind"] == "SWITCH":
        v = switch_value(rig, b["switch"]) if rig else None
        ik = (v or 0) >= 0.5
        x, y, w, h = it["rect"]
        shape = D.rrect(x, y, w, h, h / 2)
        cv.fill(shape, D.with_alpha(D.mix(base, (0, 0, 0, 1), 0.55), 0.95), 3)
        # sliding knob shows the state: left = FK, right = IK
        kx = x + w - h / 2 if ik else x + h / 2
        cv.fill(D.circle(kx, y + h / 2, h / 2 - 1.5 * k), col, 4)
        cv.text(x + (w * 0.3 if ik else w * 0.7), y + h / 2 - 4 * k, "IK" if ik else "FK", 9.5 * k,
                (1, 1, 1, 0.95), "C", 99)
        if hovered:
            cv.outline(shape, (1, 1, 1, 0.8), 1.5, 5)
        return

    sel = [n for n in it["exist"] if rig and is_selected(rig.pose.bones[n])]
    if b["kind"] == "MOVE":
        shape = D.rdiamond(cx, cy, r * 1.15)
        ring = D.rdiamond(cx, cy, r * 1.15 + 3.2 * k)
    else:
        shape = D.circle(cx, cy, r)
        ring = D.circle(cx, cy, r + 3.2 * k)
    if keyed and any(n in keyed for n in it["exist"]):
        # keyframe on the current frame: soft glow + bright ring in the key colour
        kc = tuple(p.col_key)
        glow = D.circle(cx, cy, r + 8 * k) if b["kind"] == "ROT" else D.rdiamond(cx, cy, r * 1.15 + 9 * k)
        cv.fill(glow, kc + (0.30 * (0.5 if (dim or missing) else 1),), 2, aa=False)
        kring = D.circle(cx, cy, r + 5.5 * k) if b["kind"] == "ROT" else D.rdiamond(cx, cy, r * 1.15 + 6 * k)
        cv.outline(kring, kc + (0.95,), 2.0 * k, 5)
    cv.fill(D.circle(cx + 1.2 * k, cy - 1.8 * k, r * 1.02) if b["kind"] == "ROT"
            else D.rdiamond(cx + 1.2 * k, cy - 1.8 * k, r * 1.17), (0, 0, 0, 0.35 * alpha), 3, aa=False)
    cv.fill(shape, col, 4)
    if sel:
        full = len(sel) == len(it["exist"])
        cv.outline(ring, (1, 1, 1, 1.0 if full else 0.55), 2.6 * k if full else 1.6 * k, 5)
    if STATE["edit"] and b["idx"] is not None and b["idx"] == active_idx:
        cv.outline(D.circle(cx, cy, r + 6 * k), (1, 0.55, 0.15, 1), 2 * k, 5)
    if dim or missing:
        return
    # glyphs: curved arrow = rotate, four arrows = move
    gw = max(1.2, 1.5 * k * min(1.0, r / (11 * k)))
    if b["kind"] == "ROT":
        rr = r * 0.55
        pts = D.arc(cx, cy, rr, pi * 0.62, pi * 2.38, 20)
        cv.outline(pts, gcol, gw, 6, closed=False)
        ex, ey = pts[-1]
        a = pi * 2.38 + pi / 2
        hs = max(2.0, r * 0.26)
        tip = (ex + hs * 0.9 * cos(a), ey + hs * 0.9 * sin(a))
        cv.fill([tip, (ex + hs * 0.55 * cos(a + 2.3), ey + hs * 0.55 * sin(a + 2.3)),
                 (ex + hs * 0.55 * cos(a - 2.3), ey + hs * 0.55 * sin(a - 2.3))],
                gcol, 6)
    else:
        L = r * 0.62
        hs = max(1.8, r * 0.2)
        cv.line((cx - L, cy), (cx + L, cy), gcol, gw, 6)
        cv.line((cx, cy - L), (cx, cy + L), gcol, gw, 6)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            tx, ty = cx + dx * L, cy + dy * L
            px, py = -dy, dx
            cv.fill([(tx + dx * hs * 0.6, ty + dy * hs * 0.6), (tx - dx * hs * 0.5 + px * hs, ty - dy * hs * 0.5 + py * hs),
                     (tx - dx * hs * 0.5 - px * hs, ty - dy * hs * 0.5 - py * hs)], gcol, 6)
    if p.show_labels and r >= 11 * k:
        ts = 9 * k
        tw = D.text_width(b["label"], ts)
        ty = cy - r - 13 * k
        cv.fill(D.rrect(cx - tw / 2 - 3 * k, ty - 3 * k, tw + 6 * k, ts + 5 * k, 3 * k), (0.05, 0.05, 0.06, 0.78), 7)
        cv.text(cx, ty, b["label"], ts, (0.95, 0.95, 0.95, 1), "C")


def action_state(context, key):
    """(label, is_on) for the bottom action row."""
    p = prefs()
    if key == "fk":
        return ("FK shown" if p.show_fk else "FK hidden"), p.show_fk
    if key == "curl":
        return "Curl", context.scene.tool_settings.transform_pivot_point == "INDIVIDUAL_ORIGINS"
    if key == "rig":
        sp = picker_space(context)
        on = bool(sp and sp.overlay.show_bones)
        return ("Rig shown" if on else "Rig hidden"), on
    return "Key All", False


def draw_pill(cv, F, p, it, hovered, context=None):
    k = F.k
    x, y, w, h = it["rect"]
    label = it["label"]
    base = side_color(p, it["side"]) if it.get("side") else (0.5, 0.5, 0.52, 1)
    lit = False
    if it["type"] == "tool":
        base = (1, 0.55, 0.15, 1) if it["key"] == "done" else (0.45, 0.45, 0.48, 1)
    elif it["type"] == "act":
        label, lit = action_state(context, it["key"])
        base = tuple(p.col_key) + (1,) if it["key"] == "key_all" else (0.42, 0.74, 1.0, 1)
    shape = D.rrect(x, y, w, h, 4 * k if it["type"] == "act" else h / 2)
    if lit:
        fill = D.with_alpha(D.mix(base, (1, 1, 1, 1), 0.15 if hovered else 0.0), 0.95)
        tcol = (0.06, 0.06, 0.07, 1)
    else:
        fill = D.with_alpha(D.mix(base, (0.1, 0.1, 0.1, 1), 0.35 if hovered else 0.62), 0.95)
        tcol = (1, 1, 1, 0.95)
    if it["type"] == "act" and it["key"] == "key_all":
        fill = D.with_alpha(D.mix(base, (0.1, 0.1, 0.1, 1), 0.15 if hovered else 0.35), 0.95)
        tcol = (1, 1, 1, 1)
    cv.fill(shape, fill, 3)
    cv.outline(shape, D.with_alpha(base, 0.9 if hovered else 0.55), 1.2, 4)
    if it["type"] == "act" and it["key"] == "key_all":
        dx = x + w / 2 - D.text_width(label, 11.5 * k) / 2 - 9 * k
        cv.fill(D.rdiamond(dx, y + h / 2, 5 * k, 0.15), (1, 1, 1, 0.95), 4)
    cv.text(x + w / 2 + (4 * k if it["type"] == "act" and it["key"] == "key_all" else 0),
            y + h / 2 - 4.5 * k, label, 11.5 * k, tcol, "C")


def draw_callback():
    if not STATE["show"]:
        return
    try:
        ctx = bpy.context
        area, region = ctx.area, ctx.region
        if area is None or region is None or region.type != "WINDOW":
            return
        ta = target_area(ctx.screen)
        if ta is None or ta.as_pointer() != area.as_pointer():
            return
        if window_region(area).as_pointer() != region.as_pointer():
            return
        draw_picker(ctx, region)
    except Exception:
        traceback.print_exc()


# ---------------------------------------------------------------- keys, curl, viewport helpers

def picker_space(context):
    area = target_area(context.screen) if context.screen else None
    return area.spaces.active if area else None


def _fcurves(rig):
    ad = rig.animation_data
    act = ad.action if ad else None
    if act is None:
        return None, []
    try:
        from bpy_extras import anim_utils
        cb = anim_utils.action_get_channelbag_for_slot(act, ad.action_slot)
        return act, (list(cb.fcurves) if cb else [])
    except Exception:
        return act, list(getattr(act, "fcurves", []))


def key_map(rig):
    """{bone name: set of keyed frames}, cached until the action changes."""
    act, fcurves = _fcurves(rig)
    if act is None:
        return {}
    sig = (act.as_pointer(), len(fcurves), sum(len(fc.keyframe_points) for fc in fcurves))
    if KEY_CACHE["sig"] == sig and not KEY_CACHE["dirty"]:
        return KEY_CACHE["map"]
    m = {}
    for fc in fcurves:
        dp = fc.data_path
        if not dp.startswith('pose.bones["'):
            continue
        name = dp[12:dp.find('"]', 12)]
        cnt = len(fc.keyframe_points)
        if not cnt:
            continue
        arr = [0.0] * (cnt * 2)
        fc.keyframe_points.foreach_get("co", arr)
        m.setdefault(name, set()).update(round(f, 2) for f in arr[0::2])
    KEY_CACHE.update(sig=sig, map=m, dirty=False)
    return m


def keyed_now(context, rig):
    m = key_map(rig)
    if not m:
        return set()
    sc = context.scene
    f = round(sc.frame_current + sc.frame_subframe, 2)
    return {n for n, frames in m.items() if f in frames}


def key_all(context, rig, buttons):
    if rig is None:
        return "Select a rig first"
    pbs = rig.pose.bones
    names, props = [], []
    for b in buttons:
        if b["kind"] == "SWITCH":
            if b["switch"] and b["switch"] not in props:
                props.append(b["switch"])
            continue
        names += [n for n in bone_names(b) if n in pbs]
    names = list(dict.fromkeys(names))
    for n in names:
        pb = pbs[n]
        mode = pb.rotation_mode
        rot = ("rotation_quaternion" if mode == "QUATERNION" else
               "rotation_axis_angle" if mode == "AXIS_ANGLE" else "rotation_euler")
        for path in ("location", rot, "scale"):
            try:
                pb.keyframe_insert(path, group=n)
            except Exception:
                pass
    for prop in props:
        owner = switch_owner(rig, prop)
        if owner is not None:
            try:
                owner.keyframe_insert(f'["{prop}"]', group=owner.name)
            except Exception:
                pass
    KEY_CACHE["dirty"] = True
    try:
        bpy.ops.ed.undo_push(message="Picker Key All")
    except Exception:
        pass
    redraw_all(context.screen)
    return f"Keyed {len(names)} controls + {len(props)} IK/FK switches on frame {context.scene.frame_current}"


def auto_curl(context, rig):
    """Fingers selected -> Individual Origins pivot (each joint rotates = curl). Restored afterwards."""
    if not prefs().auto_curl:
        return
    ts = context.scene.tool_settings
    sel = [pb.name for pb in rig.pose.bones if is_selected(pb)]
    fingers = bool(sel) and all("Finger" in n for n in sel)
    if fingers:
        if ts.transform_pivot_point != "INDIVIDUAL_ORIGINS":
            STATE["pivot_prev"] = ts.transform_pivot_point
            ts.transform_pivot_point = "INDIVIDUAL_ORIGINS"
            STATE["pivot_auto"] = True
    elif STATE["pivot_auto"]:
        ts.transform_pivot_point = STATE["pivot_prev"]
        STATE["pivot_auto"] = False


def do_action(context, rig, buttons, key):
    p = prefs()
    if key == "key_all":
        return key_all(context, rig, buttons)
    if key == "fk":
        p.show_fk = not p.show_fk
        return "FK buttons shown" if p.show_fk else "Inactive FK buttons hidden"
    if key == "curl":
        ts = context.scene.tool_settings
        if ts.transform_pivot_point == "INDIVIDUAL_ORIGINS":
            prev = STATE["pivot_prev"]
            ts.transform_pivot_point = prev if prev != "INDIVIDUAL_ORIGINS" else "MEDIAN_POINT"
            msg = "Curl off: pivot back to " + ts.transform_pivot_point.replace("_", " ").title()
        else:
            STATE["pivot_prev"] = ts.transform_pivot_point
            ts.transform_pivot_point = "INDIVIDUAL_ORIGINS"
            msg = "Curl on: pivot is Individual Origins"
        STATE["pivot_auto"] = False
        return msg
    if key == "rig":
        sp = picker_space(context)
        if sp is not None:
            sp.overlay.show_bones = not sp.overlay.show_bones
            return "Rig bones shown" if sp.overlay.show_bones else "Rig bones hidden: select from the picker"
    return ""


@bpy.app.handlers.persistent
def on_depsgraph(scene, depsgraph):
    for u in depsgraph.updates:
        if isinstance(u.id, bpy.types.Action):
            KEY_CACHE["dirty"] = True
            break


# ---------------------------------------------------------------- selection logic

def ensure_pose(context, rig, area, region):
    if context.mode == "POSE" and context.active_object == rig:
        return True
    if not prefs().auto_pose:
        return False
    try:
        with context.temp_override(window=context.window, area=area, region=region):
            ob = context.active_object
            if ob and ob.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            context.view_layer.objects.active = rig
            rig.select_set(True)
            bpy.ops.object.mode_set(mode="POSE")
        return True
    except Exception:
        traceback.print_exc()
        return False


def reveal(rig, pb):
    if POSE_HIDE and pb.hide:
        pb.hide = False
    elif not POSE_HIDE and pb.bone.hide:
        pb.bone.hide = False
    cols = list(pb.bone.collections)
    if cols and not any(getattr(c, "is_visible_effectively", c.is_visible) for c in cols):
        c = cols[0]
        while c is not None:
            c.is_visible = True
            c = c.parent


def select_names(context, rig, names, extend=False, toggle=False, area=None, region=None, msg="Picker Select"):
    if rig is None:
        return
    if not ensure_pose(context, rig, area, region):
        return
    pbs = rig.pose.bones
    names = [n for n in names if n in pbs]
    if toggle and names and all(is_selected(pbs[n]) for n in names):
        for n in names:
            set_selected(pbs[n], False)
    else:
        if not extend:
            for pb in pbs:
                if is_selected(pb):
                    set_selected(pb, False)
        rv = prefs().reveal_hidden
        for n in names:
            if rv:
                reveal(rig, pbs[n])
            set_selected(pbs[n], True)
        if names:
            rig.data.bones.active = rig.data.bones[names[0]]
    auto_curl(context, rig)
    try:
        bpy.ops.ed.undo_push(message=msg)
    except Exception:
        pass
    redraw_all(context.screen)


def group_names(rig, buttons, group):
    out = []
    for b in buttons:
        if b["kind"] == "SWITCH":
            continue
        if group != "all" and b["group"] != group:
            continue
        if is_dimmed(rig, b):
            continue
        out += bone_names(b)
    return out


def toggle_switch(context, rig, prop):
    pb = switch_owner(rig, prop)
    if pb is None:
        return
    v = float(pb[prop])
    new = 0.0 if v >= 0.5 else 1.0
    pb[prop] = type(pb[prop])(new) if isinstance(pb[prop], (int, float)) else new
    rig.update_tag()
    context.view_layer.update()
    try:
        bpy.ops.ed.undo_push(message="Picker IK/FK")
    except Exception:
        pass
    redraw_all(context.screen)


# ---------------------------------------------------------------- layout editing (shared with sidebar operators)

FIELDS = ("label", "kind", "side", "x", "y", "size", "bones", "group", "mode", "switch")


def write_button(item, d):
    for f in FIELDS:
        v = d.get(f, "")
        if f == "mode":
            v = v or "NONE"
        setattr(item, f, v)


def ensure_custom(rig):
    if len(rig.crp_buttons) == 0:
        for d in default_buttons():
            write_button(rig.crp_buttons.add(), d)
        rig.crp_active = -1


def selected_pose_names(rig):
    act = rig.data.bones.active
    names = [pb.name for pb in rig.pose.bones if is_selected(pb)]
    if act and act.name in names:
        names.remove(act.name)
        names.insert(0, act.name)
    return names


def guess_side(names):
    if names and all(n.endswith((".L", "_L")) for n in names):
        return "L"
    if names and all(n.endswith((".R", "_R")) for n in names):
        return "R"
    return "C"


def nice_label(names):
    if not names:
        return "New Button"
    n = names[0]
    for pre in ("FK-", "IK-", "STR-", "ROOT-", "POLE-", "TORSO-", "CHST-", "HIP-"):
        if n.startswith(pre):
            n = n[len(pre):]
            break
    n = n.replace("_", " ").replace(".L", " L").replace(".R", " R")
    return n + (f" +{len(names) - 1}" if len(names) > 1 else "")


def edit_action(context, rig, key):
    """Returns a message for the status bar / report."""
    if key == "done":
        STATE["edit"] = False
        redraw_all(context.screen)
        return "Layout saved in this .blend (on the rig object)"
    if rig is None:
        return "Select a rig first"
    ensure_custom(rig)
    btns = rig.crp_buttons
    act = rig.crp_active
    names = selected_pose_names(rig)
    if key in ("add_rot", "add_move"):
        it = btns.add()
        write_button(it, dict(label=nice_label(names), kind="ROT" if key == "add_rot" else "MOVE",
                              side=guess_side(names), x=40.0, y=440.0, size=12.0, bones=",".join(names),
                              group="custom", mode="", switch=""))
        rig.crp_active = len(btns) - 1
        msg = f"Added '{it.label}' at the top-left. Drag it into place."
    elif key == "assign":
        if not (0 <= act < len(btns)):
            return "Click a button first"
        btns[act].bones = ",".join(names)
        msg = f"Assigned {len(names)} bone(s) to '{btns[act].label}'"
    elif key == "mirror":
        if not (0 <= act < len(btns)):
            return "Click a button first"
        src = {f: getattr(btns[act], f) for f in FIELDS}
        src["mode"] = "" if src["mode"] == "NONE" else src["mode"]
        m = mirror_button(src)
        it = btns.add()
        write_button(it, m)
        rig.crp_active = len(btns) - 1
        msg = f"Mirrored to '{m['label']}'"
    elif key == "delete":
        if not (0 <= act < len(btns)):
            return "Click a button first"
        lab = btns[act].label
        btns.remove(act)
        rig.crp_active = -1
        msg = f"Deleted '{lab}'"
    elif key == "done":
        STATE["edit"] = False
        msg = "Layout saved in this .blend (on the rig object)"
    else:
        return ""
    try:
        bpy.ops.ed.undo_push(message="Picker Edit")
    except Exception:
        pass
    redraw_all(context.screen)
    return msg


# ---------------------------------------------------------------- modal operator

class CRPICKER_OT_toggle(bpy.types.Operator):
    """Show or hide the floating CloudRig picker in this 3D View"""
    bl_idname = "crpicker.toggle"
    bl_label = "Toggle Picker"

    def invoke(self, context, event):
        if STATE["show"] and op_alive():
            # already open: move it to this viewport, or close it if it's already here
            if context.area and context.area.type == "VIEW_3D" and context.area.as_pointer() != STATE["area_ptr"]:
                STATE["area_ptr"] = context.area.as_pointer()
            else:
                STATE["show"] = False
            redraw_all(context.screen)
            return {"FINISHED"}
        if context.area and context.area.type == "VIEW_3D":
            STATE["area_ptr"] = context.area.as_pointer()
        else:
            target_area(context.screen)
        STATE.update(show=True, op=self, hover=None, drag=None)
        context.window_manager.modal_handler_add(self)
        redraw_all(context.screen)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not STATE["show"]:
            STATE["op"] = None
            STATE["drag"] = None
            redraw_all(context.screen)
            return {"CANCELLED"}
        try:
            return handle_event(context, event)
        except Exception:
            traceback.print_exc()
            STATE["drag"] = None
            return {"PASS_THROUGH"}


PASS = {"PASS_THROUGH"}
EAT = {"RUNNING_MODAL"}


def handle_event(context, event):
    screen = context.window.screen if context.window else None
    area = target_area(screen)
    if area is None:
        return PASS
    region = window_region(area)
    if region is None:
        return PASS
    mx, my = event.mouse_x - region.x, event.mouse_y - region.y
    drag = STATE["drag"]
    inside_region = 0 <= mx <= region.width and 0 <= my <= region.height

    if drag is None and not inside_region:
        if STATE["hover"] is not None:
            STATE["hover"] = None
            area.tag_redraw()
        return PASS

    rig = find_rig(context)
    F = make_frame(region.width, region.height)
    buttons = get_buttons(rig)
    items = build_items(F, rig, buttons)
    k = F.k

    # ----- dragging states
    if drag is not None:
        if event.type in ("MOUSEMOVE", "INBETWEEN_MOUSEMOVE"):
            kind = drag["kind"]
            if kind == "panel":
                STATE["pos"][0] = drag["pos0"][0] + (mx - drag["m0"][0])
                STATE["pos"][1] = drag["pos0"][1] - (my - drag["m0"][1])
            elif kind == "scale":
                p = prefs()
                new = drag["scale0"] * max(0.3, (mx - F.x) / max(1, drag["w0"]))
                p.scale = min(2.5, max(0.5, new))
            elif kind == "box":
                drag["cur"] = (mx, my)
            elif kind == "button" and rig is not None:
                it = rig.crp_buttons[drag["idx"]]
                dx, dy = from_px(F, mx - drag["off"][0], my - drag["off"][1])
                snap = 2.0 if not event.ctrl else 10.0
                it.x = round(min(max(dx, 0), CANVAS_W) / snap) * snap
                it.y = round(min(max(dy, 0), CANVAS_H) / snap) * snap
                drag["moved"] = True
            area.tag_redraw()
            return EAT
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            finish_drag(context, rig, buttons, items, drag, event, area, region)
            STATE["drag"] = None
            area.tag_redraw()
            return EAT
        if event.type in ("RIGHTMOUSE", "ESC") and event.value == "PRESS":
            STATE["drag"] = None
            area.tag_redraw()
            return EAT
        return EAT

    panel_rect = (F.x, F.y, F.w, F.h)
    over = in_rect(mx, my, panel_rect)
    target = hit(items, mx, my) if over else None
    key = item_key(target)
    if key != STATE["hover"]:
        STATE["hover"] = key
        STATE["status"] = ""
        area.tag_redraw()
    if not over:
        return PASS

    # ----- wheel
    if event.type in ("WHEELUPMOUSE", "WHEELDOWNMOUSE"):
        up = event.type == "WHEELUPMOUSE"
        if event.ctrl:
            p = prefs()
            p.scale = min(2.5, max(0.5, p.scale * (1.08 if up else 1 / 1.08)))
            area.tag_redraw()
            return EAT
        if STATE["edit"] and target and target["type"] == "btn" and rig is not None:
            ensure_custom(rig)
            idx = target["b"]["idx"]
            if idx is None:
                idx = next((i for i, b in enumerate(rig.crp_buttons) if b.label == target["b"]["label"]), None)
            if idx is not None:
                b = rig.crp_buttons[idx]
                b.size = min(40, max(4, b.size + (1 if up else -1)))
                area.tag_redraw()
            return EAT
        return EAT if STATE["edit"] else PASS

    if event.type == "LEFTMOUSE" and event.value in ("PRESS", "DOUBLE_CLICK"):
        STATE["status"] = ""
        if target is None:
            return EAT
        t = target["type"]
        if t == "hdr":
            if target["key"] == "close":
                STATE["show"] = False
            elif target["key"] == "collapse":
                STATE["collapsed"] = not STATE["collapsed"]
            elif target["key"] == "edit":
                STATE["edit"] = not STATE["edit"]
                if STATE["edit"] and rig is not None:
                    try:
                        ensure_custom(rig)
                    except Exception:
                        STATE["edit"] = False
                        traceback.print_exc()
            redraw_all(context.screen)
            return EAT
        if t == "grip":
            STATE["drag"] = dict(kind="scale", scale0=prefs().scale, w0=F.w)
            return EAT
        if t == "header":
            STATE["drag"] = dict(kind="panel", m0=(mx, my), pos0=tuple(STATE["pos"]))
            return EAT
        if t == "btn":
            b = target["b"]
            if STATE["edit"]:
                if rig is None:
                    return EAT
                ensure_custom(rig)
                idx = b["idx"]
                if idx is None:
                    idx = next((i for i, x in enumerate(rig.crp_buttons) if x.label == b["label"]), 0)
                rig.crp_active = idx
                STATE["drag"] = dict(kind="button", idx=idx, off=(mx - target["cx"], my - target["cy"]), moved=False)
                area.tag_redraw()
                return EAT
            if b["kind"] == "SWITCH":
                toggle_switch(context, rig, b["switch"])
                return EAT
            now = time.monotonic()
            last = STATE.get("last_click")
            if last and last[0] == key and now - last[1] < 0.45:
                # double-click: the whole limb / group this button belongs to
                STATE["last_click"] = None
                select_names(context, rig, group_names(rig, buttons, b["group"]), extend=event.shift,
                             area=area, region=region)
                return EAT
            STATE["last_click"] = (key, now)
            select_names(context, rig, bone_names(b), extend=event.shift, toggle=event.shift,
                         area=area, region=region)
            return EAT
        if t == "pill":
            if target["key"] == "none":
                select_names(context, rig, [], extend=False, area=area, region=region, msg="Picker Deselect")
            else:
                select_names(context, rig, group_names(rig, buttons, target["key"]), extend=event.shift,
                             area=area, region=region)
            return EAT
        if t == "tool":
            msg = edit_action(context, rig, target["key"])
            STATE["status"] = msg
            area.tag_redraw()
            return EAT
        if t == "act":
            STATE["status"] = do_action(context, rig, buttons, target["key"])
            redraw_all(context.screen)
            return EAT
        if t == "canvas" and not STATE["edit"]:
            STATE["drag"] = dict(kind="box", start=(mx, my), cur=(mx, my), shift=event.shift)
            return EAT
        return EAT

    if event.type == "LEFTMOUSE" and event.value in ("RELEASE", "CLICK"):
        return EAT
    if event.type in ("MOUSEMOVE", "INBETWEEN_MOUSEMOVE"):
        return PASS
    # Keys (G, R, S, I, Ctrl+Z ...) and other events keep working while hovering the picker
    return PASS


def finish_drag(context, rig, buttons, items, drag, event, area, region):
    kind = drag["kind"]
    if kind == "box":
        x0, y0 = drag["start"]
        x1, y1 = drag["cur"]
        if abs(x1 - x0) < 4 and abs(y1 - y0) < 4:
            if not drag["shift"]:   # click on empty space = deselect all
                select_names(context, rig, [], area=area, region=region, msg="Picker Deselect")
            return
        lo_x, hi_x = sorted((x0, x1))
        lo_y, hi_y = sorted((y0, y1))
        names = []
        for it in items:
            if it["type"] == "btn" and it["b"]["kind"] != "SWITCH" and lo_x <= it["cx"] <= hi_x and lo_y <= it["cy"] <= hi_y:
                if rig is not None and is_dimmed(rig, it["b"]):
                    continue
                names += it["exist"]
        select_names(context, rig, names, extend=drag["shift"], area=area, region=region, msg="Picker Box Select")
    elif kind == "button" and drag.get("moved"):
        try:
            bpy.ops.ed.undo_push(message="Picker Move Button")
        except Exception:
            pass
    elif kind == "scale":
        context.preferences.is_dirty = True


# ---------------------------------------------------------------- file load: re-open the picker

def reopen_after_load():
    wm = bpy.context.window_manager
    for win in wm.windows:
        area = target_area(win.screen)
        if area is None:
            continue
        region = window_region(area)
        try:
            with bpy.context.temp_override(window=win, area=area, region=region):
                bpy.ops.crpicker.toggle("INVOKE_DEFAULT")
        except Exception:
            traceback.print_exc()
        break
    return None


@bpy.app.handlers.persistent
def on_load_post(*_args):
    was_open = STATE["show"]
    STATE.update(show=False, op=None, drag=None, hover=None, edit=False, area_ptr=0, pivot_auto=False)
    KEY_CACHE.update(sig=None, map={}, dirty=True)
    _SWITCH_CACHE.clear()
    if was_open and prefs().reopen_on_load:
        bpy.app.timers.register(reopen_after_load, first_interval=0.3)
