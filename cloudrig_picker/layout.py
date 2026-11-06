# Picker layout data: the mannequin silhouette and the default CloudRig "Cloud Human" buttons.
# Design space is a canvas CANVAS_W x CANVAS_H units, origin bottom-left, y up.
# The figure faces the viewer, so the character's RIGHT side (.R) is on the screen LEFT.

import re
from math import cos, sin, radians

CANVAS_W = 360.0
CANVAS_H = 480.0
MID = CANVAS_W / 2


def mx(x):
    """Mirror an x coordinate across the figure's centre line."""
    return CANVAS_W - x


# ---------------------------------------------------------------- mannequin
# ('ellipse', cx, cy, rx, ry) | ('capsule', x1, y1, x2, y2, r) | ('circle', cx, cy, r)
# A 'j' after the shape name marks a joint ball (drawn a shade darker), 'h' marks the head.

HAND_C = (86.0, 198.0)          # right palm centre (screen left)
FINGER_R = 38.0
FINGER_ANGLES = (-35, -62, -90, -118, -145)   # thumb .. pinky, right hand
FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")


def finger_pos(i, mirror=False):
    a = radians(FINGER_ANGLES[i])
    x, y = HAND_C[0] + FINGER_R * cos(a), HAND_C[1] - 2 + FINGER_R * sin(a)
    return (mx(x), y) if mirror else (x, y)


def _side_shapes(mirror):
    m = (lambda x: mx(x)) if mirror else (lambda x: x)
    s = [
        # arm
        ("circlej", m(139), 358, 16),
        ("capsule", m(133), 348, m(104), 262, 13),
        ("circlej", m(102), 260, 11),
        ("capsule", m(102), 260, m(88), 212, 10.5),
        ("ellipse", m(HAND_C[0]), HAND_C[1], 13, 16),
        # leg
        ("capsule", m(161), 220, m(154), 130, 19),
        ("circlej", m(153), 130, 14),
        ("capsule", m(153), 130, m(150), 54, 13.5),
        ("circlej", m(150), 50, 10.5),                    # ankle
        ("capsule", m(152), 36, m(128), 24, 11.5),        # foot, turned out
        ("ellipse", m(122), 22, 13, 9.5),                 # toes
    ]
    # fingers: thin capsules from the palm toward each finger button
    for i in range(5):
        fx, fy = finger_pos(i, mirror)
        hx, hy = (m(HAND_C[0]), HAND_C[1] - 4)
        tx, ty = hx + (fx - hx) * 0.78, hy + (fy - hy) * 0.78
        s.append(("capsule", hx + (fx - hx) * 0.35, hy + (fy - hy) * 0.35, tx, ty, 4.2))
    return s


MANNEQUIN = (
    [
        ("ellipsef", MID, 12, 78, 9),            # floor shadow
        ("capsule", MID, 372, MID, 388, 11.5),      # neck
        ("ellipse", MID, 336, 50, 36),            # chest
        ("ellipse", MID, 284, 34, 30),            # abdomen
        ("ellipse", MID, 228, 44, 26),            # pelvis
        ("ellipseh", MID, 420, 25, 30),           # head
    ]
    + _side_shapes(False)
    + _side_shapes(True)
)


# ---------------------------------------------------------------- default buttons
# kind: ROT (rotate, round), MOVE (translate, diamond), SWITCH (IK/FK pill)
# side: C centre, R right, L left, X extra (hair etc.)
# mode: '' always active | 'FK' / 'IK' -> dimmed when the limb's switch says otherwise

def B(label, kind, side, x, y, size, bones, group, mode="", switch=""):
    return dict(label=label, kind=kind, side=side, x=float(x), y=float(y), size=float(size),
                bones=bones if isinstance(bones, str) else ",".join(bones),
                group=group, mode=mode, switch=switch)


def _right_side():
    arm, leg = "ik_right_arm", "ik_right_leg"
    out = [
        B("Shoulder R", "ROT", "R", 140, 362, 11, "FK-Shoulder.R", "arm_r"),
        B("Upper Arm R (FK)", "ROT", "R", 118, 318, 13, "FK-UpperArm.R", "arm_r", "FK", arm),
        B("Forearm R (FK)", "ROT", "R", 100, 258, 13, "FK-Forearm.R", "arm_r", "FK", arm),
        B("Hand R (FK)", "ROT", "R", 88, 210, 11, "FK-Hand.R", "arm_r", "FK", arm),
        B("Hand R (IK)", "MOVE", "R", 54, 224, 14, "IK-Hand.R", "arm_r", "IK", arm),
        B("Elbow Pole R (IK)", "MOVE", "R", 66, 292, 9, "POLE-Arm.R", "arm_r", "IK", arm),
        B("Arm R IK/FK", "SWITCH", "R", 62, 344, 10, "", "arm_r", "", arm),
        B("Thigh R (FK)", "ROT", "R", 156, 190, 13, "FK-Thigh.R", "leg_r", "FK", leg),
        B("Shin R (FK)", "ROT", "R", 152, 130, 13, "FK-Knee.R", "leg_r", "FK", leg),
        B("Foot R (FK)", "ROT", "R", 150, 64, 12, "FK-Foot.R", "leg_r", "FK", leg),
        B("Toes R", "ROT", "R", 114, 20, 9, "FK-Toes.R", "leg_r"),
        B("Foot R (IK)", "MOVE", "R", 140, 30, 14, "IK-Foot.R", "leg_r", "IK", leg),
        B("Knee Pole R (IK)", "MOVE", "R", 120, 132, 9, "POLE-Leg.R", "leg_r", "IK", leg),
        B("Foot Roll R (IK)", "ROT", "R", 104, 46, 9, "ROLL-M-Foot.R", "leg_r", "IK", leg),
        B("Leg R IK/FK", "SWITCH", "R", 122, 96, 10, "", "leg_r", "", leg),
    ]
    for i, f in enumerate(FINGERS):
        x, y = finger_pos(i)
        bones = [f"FK-Finger_{f}{n}.R" for n in (1, 2, 3)]
        out.append(B(f"{f} R", "ROT", "R", x, y, 8, bones, "hand_r"))
    return out


def mirror_name(s):
    """Swap .L/.R style suffixes and left/right words."""
    if not s:
        return s
    out = []
    for part in s.split(","):
        p = part.strip()
        if p.endswith(".R"):
            p = p[:-2] + ".L"
        elif p.endswith(".L"):
            p = p[:-2] + ".R"
        elif p.endswith("_R"):
            p = p[:-2] + "_L"
        elif p.endswith("_L"):
            p = p[:-2] + "_R"
        out.append(p)
    s = ",".join(out)
    if "right" in s:
        s = s.replace("right", "left")
    elif "left" in s:
        s = s.replace("left", "right")
    return s


def mirror_button(b):
    m = dict(b)
    m["x"] = mx(b["x"])
    m["bones"] = mirror_name(b["bones"])
    m["switch"] = mirror_name(b["switch"])
    m["side"] = {"R": "L", "L": "R"}.get(b["side"], b["side"])
    g = b["group"]
    m["group"] = g[:-2] + "_l" if g.endswith("_r") else g[:-2] + "_r" if g.endswith("_l") else g
    lab = b["label"]
    if re.search(r"\bR\b", lab):
        m["label"] = re.sub(r"\bR\b", "L", lab)
    else:
        m["label"] = re.sub(r"\bL\b", "R", lab)
    return m


def default_layout():
    sp = "Spine_ik"
    centre = [
        B("Head", "ROT", "C", MID, 420, 18, "FK-Head", "head"),
        B("Neck", "ROT", "C", MID, 381, 10, "FK-Neck", "head"),
        B("Chest (IK)", "MOVE", "C", MID, 342, 16, "CHST-Spine", "torso", "IK", sp),
        B("Chest (FK)", "ROT", "C", MID, 312, 11, "FK-Chest", "torso", "FK", sp),
        B("Spine (FK)", "ROT", "C", MID, 286, 11, "FK-Spine", "torso", "FK", sp),
        B("Torso / COG", "MOVE", "C", MID, 258, 19, "TORSO-Spine", "torso"),
        B("Hips", "ROT", "C", MID, 226, 14, "HIP-Spine", "torso"),
        B("Lower Hips", "ROT", "C", MID, 202, 8, "HipsLower-Spine", "torso"),
        B("Spine IK/FK", "SWITCH", "C", 232, 288, 10, "", "torso", "", sp),
        B("Root", "MOVE", "C", MID, 14, 15, "root", "root"),
    ]
    hair = [B(f"Ponytail {i}", "ROT", "X", x, y, 8, f"FK-Ponytail{i}", "hair")
            for i, (x, y) in enumerate([(204, 444), (222, 452), (240, 448), (255, 436)], 1)]
    right = _right_side()
    left = [mirror_button(b) for b in right]
    return centre + hair + right + left


# Footer quick-select pills: (label, group key, side colour). Rows are written for the
# "seen from behind" view (character's left on the screen left); front view swaps L/R.
PILL_ROWS = [
    [("All", "all", "C"), ("Torso", "torso", "C"), ("Head", "head", "C"), ("Hair", "hair", "X")],
    [("Arm L", "arm_l", "L"), ("Fingers L", "hand_l", "L"), ("Fingers R", "hand_r", "R"), ("Arm R", "arm_r", "R")],
    [("Leg L", "leg_l", "L"), ("Root", "root", "C"), ("None", "none", ""), ("Leg R", "leg_r", "R")],
]


def pill_rows(back_view=True):
    """Left-side pills in the left columns, right-side pills in the right columns."""
    if back_view:
        return PILL_ROWS
    return [PILL_ROWS[0]] + [list(reversed(r)) for r in PILL_ROWS[1:]]


# Bottom action row: key all, hide FK, curl pivot, hide rig bones
ACTIONS = [("Key All", "key_all"), ("FK", "fk"), ("Curl", "curl"), ("Rig", "rig")]

EDIT_TOOLS = [
    ("+ Rotate", "add_rot"), ("+ Move", "add_move"), ("Assign", "assign"),
    ("Mirror", "mirror"), ("Delete", "delete"), ("Done", "done"),
]
