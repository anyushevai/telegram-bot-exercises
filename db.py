import sqlite3
from contextlib import contextmanager
from config import DB_PATH

SYSTEM_TOPICS = [
    "10 способов классно провести день рождения",
    "10 способов заработать дополнительные деньги не уходя с основной работы",
    "10 способов улучшить своё настроение прямо сейчас",
    "10 проектов, которые хочется запустить на моей текущей работе",
    "10 навыков, которые хочется освоить в этом году",
    "10 идей для новых направлений бизнеса на моей текущей работе",
    "10 способов познакомиться с интересными людьми",
    "10 способов провести отпуск незабываемо",
    "10 тем для будущих упражнений «Список 10»",
    "10 суперспособностей, которые я хотел бы иметь",
    "10 вещей, которые я хочу попробовать впервые",
    "10 идей новых блюд, которые хочется приготовить",
    "10 способов заработать 100 долларов за один день",
    "10 сюжетов книг о космосе",
    "10 идей необычных коллабораций",
    "10 новых бизнесов для Яндекса",
    "10 продуктов, которых не хватает в мире",
    "10 изобретений, которые изменили бы мою повседневную жизнь",
    "10 способов монетизировать хобби",
    "10 вещей, которые я сделаю если выиграю миллион",
    "10 идей для подкаста",
    "10 мест в мире, где я хотел бы прожить целый год",
    "10 способов сделать понедельник счастливым",
    "10 идей заработать 100 долл. за следующий час",
    "10 новых способов провести воскресный вечер",
]


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                joined_at   TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS topics (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                text        TEXT    NOT NULL UNIQUE,
                source      TEXT    NOT NULL DEFAULT 'system',
                owner_id    INTEGER,
                created_at  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS exercises (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                topic_text   TEXT    NOT NULL,
                topic_id     INTEGER,
                started_at   TEXT    DEFAULT (datetime('now')),
                completed_at TEXT,
                is_completed INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS exercise_items (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                exercise_id  INTEGER NOT NULL,
                item_number  INTEGER NOT NULL,
                text         TEXT    NOT NULL
            );
        """)
        for topic in SYSTEM_TOPICS:
            conn.execute(
                "INSERT OR IGNORE INTO topics (text, source) VALUES (?, 'system')",
                (topic,),
            )


def upsert_user(user_id: int, username: str, first_name: str) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO users (id, username, first_name) VALUES (?, ?, ?)
               ON CONFLICT(id) DO UPDATE
               SET username=excluded.username, first_name=excluded.first_name""",
            (user_id, username, first_name),
        )


def get_random_topic(user_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            """SELECT id, text, source FROM topics
               WHERE (owner_id IS NULL OR owner_id = ?)
                 AND id NOT IN (
                     SELECT DISTINCT topic_id FROM exercises
                     WHERE user_id = ? AND is_completed = 1 AND topic_id IS NOT NULL
                 )
               ORDER BY RANDOM() LIMIT 1""",
            (user_id, user_id),
        ).fetchone()
        if row:
            return dict(row)
        row = conn.execute(
            "SELECT id, text, source FROM topics WHERE owner_id IS NULL OR owner_id = ? ORDER BY RANDOM() LIMIT 1",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def get_topic_by_id(topic_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, text, source FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
        return dict(row) if row else None


def get_user_topics(user_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, text FROM topics WHERE owner_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def add_topic(text: str, source: str, owner_id: int | None = None) -> int | None:
    try:
        with _conn() as conn:
            cur = conn.execute(
                "INSERT INTO topics (text, source, owner_id) VALUES (?, ?, ?)",
                (text, source, owner_id),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def start_exercise(user_id: int, topic_text: str, topic_id: int | None = None) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO exercises (user_id, topic_text, topic_id) VALUES (?, ?, ?)",
            (user_id, topic_text, topic_id),
        )
        return cur.lastrowid


def add_exercise_item(exercise_id: int, item_number: int, text: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO exercise_items (exercise_id, item_number, text) VALUES (?, ?, ?)",
            (exercise_id, item_number, text),
        )


def complete_exercise(exercise_id: int) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE exercises SET is_completed=1, completed_at=datetime('now') WHERE id=?",
            (exercise_id,),
        )


def get_exercise(exercise_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM exercises WHERE id = ?", (exercise_id,)
        ).fetchone()
        return dict(row) if row else None


def get_exercise_items(exercise_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT item_number, text FROM exercise_items WHERE exercise_id=? ORDER BY item_number",
            (exercise_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_user_stats(user_id: int) -> dict:
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM exercises WHERE user_id=? AND is_completed=1",
            (user_id,),
        ).fetchone()
        return {"completed": row["cnt"]}
