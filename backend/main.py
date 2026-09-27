from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = Path(__file__).resolve().parent
DB_PATH = BACKEND_DIR / "game.db"
PICASSO_DIR = ROOT / "picasso_images"
FRONTEND_DIST = ROOT / "frontend" / "dist" / "frontend" / "browser"

CATEGORIES = [
    {"id": "trump", "name": "Trump Quote or AI?", "short_name": "Trump", "icon": "🎙️", "color": "#ef6a5b"},
    {"id": "picasso", "name": "Picasso or AI?", "short_name": "Picasso", "icon": "🎨", "color": "#5f8fe8"},
    {"id": "bible", "name": "Old Testament or AI?", "short_name": "Old Testament", "icon": "📜", "color": "#9a72d8"},
    {"id": "arrest", "name": "Real Reason for Arrest or AI?", "short_name": "Arrest", "icon": "🚨", "color": "#30a78b"},
    {"id": "special", "name": "Special Category", "short_name": "Special", "icon": "✨", "color": "#e29f2d", "double_points": True},
]
SELECTABLE_CATEGORY_IDS = {category["id"] for category in CATEGORIES if not category.get("double_points")}
with (BACKEND_DIR / "questions.json").open("r", encoding="utf-8") as file:
    RAW_QUESTIONS = json.load(file)

# Rotate through all five categories in each of the three rounds.
QUESTIONS = [
    next(q for q in RAW_QUESTIONS if q["category_id"] == category["id"] and q["id"].endswith(f"-{round_no}"))
    for round_no in range(1, 4)
    for category in CATEGORIES
]

db_lock = Lock()
app = FastAPI(title="Real or AI Game", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class NewGameRequest(BaseModel):
    player_count: int = Field(ge=6, le=100)


class CategoryRequest(BaseModel):
    category_id: str


class ScoreRequest(BaseModel):
    delta: int = Field(ge=-20, le=20)


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    with connect() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS game_state (
                id INTEGER PRIMARY KEY CHECK (id = 1), phase TEXT NOT NULL,
                player_count INTEGER NOT NULL DEFAULT 0,
                current_question INTEGER NOT NULL DEFAULT 0,
                revealed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0, category_id TEXT
            );
            CREATE TABLE IF NOT EXISTS team_members (
                team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                person_number INTEGER NOT NULL,
                PRIMARY KEY (team_id, person_number)
            );
            INSERT OR IGNORE INTO game_state (id, phase) VALUES (1, 'setup');
        """)


def category_by_id(category_id: str | None) -> dict | None:
    return next((category for category in CATEGORIES if category["id"] == category_id), None)


def build_state(connection: sqlite3.Connection) -> dict:
    game = connection.execute("SELECT * FROM game_state WHERE id = 1").fetchone()
    team_rows = connection.execute("SELECT * FROM teams ORDER BY score DESC, id ASC").fetchall()
    teams = []
    for rank, team in enumerate(team_rows, start=1):
        members = connection.execute(
            "SELECT person_number FROM team_members WHERE team_id = ? ORDER BY person_number", (team["id"],)
        ).fetchall()
        teams.append({
            "id": team["id"], "name": team["name"], "score": team["score"], "rank": rank,
            "category_id": team["category_id"], "category": category_by_id(team["category_id"]),
            "members": [member["person_number"] for member in members],
        })

    current_question = None
    if game["phase"] == "quiz" and 0 <= game["current_question"] < len(QUESTIONS):
        current_question = dict(QUESTIONS[game["current_question"]])
        current_question["category"] = category_by_id(current_question["category_id"])
        current_question["round"] = game["current_question"] // len(CATEGORIES) + 1
        current_question["number"] = game["current_question"] + 1
        current_question["total"] = len(QUESTIONS)

    return {
        "phase": game["phase"], "player_count": game["player_count"],
        "current_question_index": game["current_question"], "revealed": bool(game["revealed"]),
        "categories": CATEGORIES, "teams": teams, "current_question": current_question,
    }


def reset_game(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM team_members")
    connection.execute("DELETE FROM teams")
    connection.execute("DELETE FROM sqlite_sequence WHERE name = 'teams'")
    connection.execute("UPDATE game_state SET phase='setup', player_count=0, current_question=0, revealed=0 WHERE id=1")


initialize_database()


@app.get("/api/state")
def get_state() -> dict:
    with connect() as connection:
        return build_state(connection)


@app.post("/api/games")
def new_game(payload: NewGameRequest) -> dict:
    with db_lock, connect() as connection:
        reset_game(connection)
        players = list(range(1, payload.player_count + 1))
        random.SystemRandom().shuffle(players)
        team_count = payload.player_count // 3
        sizes = [3] * team_count
        for index in range(payload.player_count % 3):
            sizes[index] += 1
        cursor = 0
        for team_number, size in enumerate(sizes, start=1):
            team = connection.execute("INSERT INTO teams (name) VALUES (?)", (f"Team {team_number}",))
            for person_number in players[cursor:cursor + size]:
                connection.execute("INSERT INTO team_members VALUES (?, ?)", (team.lastrowid, person_number))
            cursor += size
        connection.execute(
            "UPDATE game_state SET phase='assignment', player_count=?, current_question=0, revealed=0 WHERE id=1",
            (payload.player_count,),
        )
        return build_state(connection)


@app.post("/api/assignment/continue")
def continue_from_assignment() -> dict:
    with db_lock, connect() as connection:
        phase = connection.execute("SELECT phase FROM game_state WHERE id=1").fetchone()[0]
        if phase != "assignment":
            raise HTTPException(409, "The game is not on the team assignment screen.")
        connection.execute("UPDATE game_state SET phase='categories' WHERE id=1")
        return build_state(connection)


@app.put("/api/teams/{team_id}/category")
def select_category(team_id: int, payload: CategoryRequest) -> dict:
    if payload.category_id not in SELECTABLE_CATEGORY_IDS:
        raise HTTPException(400, "Unknown category.")
    with db_lock, connect() as connection:
        result = connection.execute("UPDATE teams SET category_id=? WHERE id=?", (payload.category_id, team_id))
        if result.rowcount == 0:
            raise HTTPException(404, "Team not found.")
        return build_state(connection)


@app.post("/api/quiz/start")
def start_quiz() -> dict:
    with db_lock, connect() as connection:
        phase = connection.execute("SELECT phase FROM game_state WHERE id=1").fetchone()[0]
        missing = connection.execute("SELECT COUNT(*) FROM teams WHERE category_id IS NULL").fetchone()[0]
        if phase != "categories" or missing:
            raise HTTPException(409, "Every team must choose a category before the quiz starts.")
        connection.execute("UPDATE game_state SET phase='quiz', current_question=0, revealed=0 WHERE id=1")
        return build_state(connection)


@app.post("/api/teams/{team_id}/score")
def update_score(team_id: int, payload: ScoreRequest) -> dict:
    with db_lock, connect() as connection:
        result = connection.execute("UPDATE teams SET score=score+? WHERE id=?", (payload.delta, team_id))
        if result.rowcount == 0:
            raise HTTPException(404, "Team not found.")
        return build_state(connection)


@app.post("/api/quiz/reveal")
def reveal_answer() -> dict:
    with db_lock, connect() as connection:
        if connection.execute("SELECT phase FROM game_state WHERE id=1").fetchone()[0] != "quiz":
            raise HTTPException(409, "There is no active question.")
        connection.execute("UPDATE game_state SET revealed=1 WHERE id=1")
        return build_state(connection)


@app.post("/api/quiz/next")
def next_question() -> dict:
    with db_lock, connect() as connection:
        game = connection.execute("SELECT * FROM game_state WHERE id=1").fetchone()
        if game["phase"] != "quiz" or not game["revealed"]:
            raise HTTPException(409, "Reveal the answer before continuing.")
        if game["current_question"] >= len(QUESTIONS) - 1:
            connection.execute("UPDATE game_state SET phase='results' WHERE id=1")
        else:
            connection.execute("UPDATE game_state SET current_question=current_question+1, revealed=0 WHERE id=1")
        return build_state(connection)


@app.post("/api/games/reset")
def clear_game() -> dict:
    with db_lock, connect() as connection:
        reset_game(connection)
        return build_state(connection)


app.mount("/picasso_images", StaticFiles(directory=PICASSO_DIR), name="picasso-images")

if FRONTEND_DIST.exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    def angular_app(full_path: str):
        requested = FRONTEND_DIST / full_path
        if full_path and requested.is_file():
            return FileResponse(requested)
        return FileResponse(FRONTEND_DIST / "index.html")

