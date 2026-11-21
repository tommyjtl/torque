"""Transfer movement experience without transferring a level layout."""

import sqlite3
from contextlib import closing

TRAVERSAL = frozenset(
    (
        "advance",
        "advance_fire",
        "follow_route",
        "back_up",
        "strafe_left",
        "strafe_right",
        "jump_forward",
    )
)
CLEARANCE = frozenset(
    ("walkable", "jump_up", "jump_across", "too_low", "too_high", "unclear", "stalled_forward")
)


class SkillBook:
    def __init__(self, directory):
        self.path = directory / "traversal-skills.sqlite3"
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS experience (
                clearance TEXT NOT NULL, action TEXT NOT NULL, changed INTEGER NOT NULL,
                stalled INTEGER NOT NULL, PRIMARY KEY (clearance, action))""")
            db.commit()

    def record(self, clearance, action, moved):
        if clearance not in CLEARANCE or action not in TRAVERSAL:
            return
        with closing(sqlite3.connect(self.path)) as db:
            db.execute(
                """INSERT INTO experience VALUES (?, ?, ?, ?)
                ON CONFLICT(clearance,action) DO UPDATE SET
                changed=changed+excluded.changed, stalled=stalled+excluded.stalled""",
                (clearance, action, int(moved), int(not moved)),
            )
            db.commit()

    def hints(self, clearance=None):
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                """SELECT clearance,action,changed,changed+stalled AS attempts
                FROM experience WHERE changed+stalled >= 3 AND (clearance=? OR ? IS NULL)
                ORDER BY attempts DESC,clearance,action LIMIT 4""",
                (clearance, clearance),
            ).fetchall()
        return [
            f"{c}: {a} changed the settled view in {success}/{n} trials"
            for c, a, success, n in rows
        ]
