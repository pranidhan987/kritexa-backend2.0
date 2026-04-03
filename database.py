import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "kritexa.db")

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Enables accessing columns by name
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initializes the SQLite database with the required schema."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Create users table for authentication
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL, -- 'teacher' or 'student'
                roll_number TEXT UNIQUE -- Only for students
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roll_number TEXT NOT NULL,
                question_number TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT 'General',
                score REAL NOT NULL,
                max_score REAL NOT NULL,
                accuracy REAL NOT NULL,
                feedback TEXT NOT NULL,
                improvement_suggestions TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (roll_number) REFERENCES users(roll_number)
            )
        ''')
        
        # Add nested scores columns, catching exception if they already exist
        try:
            cursor.execute("ALTER TABLE results ADD COLUMN semantic_match_score REAL DEFAULT 0.0")
            cursor.execute("ALTER TABLE results ADD COLUMN keyword_match_score REAL DEFAULT 0.0")
            cursor.execute("ALTER TABLE results ADD COLUMN structure_quality_score REAL DEFAULT 0.0")
        except sqlite3.OperationalError:
            pass
            
        conn.commit()

def save_evaluation(roll_number: str, evaluation_data: dict):
    """Saves evaluation results and suggestions for a specific roll number."""
    results_list = evaluation_data.get("results", [])
    if not results_list:
        return
        
    import json
    subject_feedback = evaluation_data.get("subject_feedback", {})
    overall_feedback = evaluation_data.get("overall_feedback", {})
    combined_feedback = {
        "subject_feedback": subject_feedback,
        "overall_feedback": overall_feedback,
        "legacy": evaluation_data.get("improvement_suggestions", [])
    }
    improvement_suggestions_str = json.dumps(combined_feedback)
        
    with get_db_connection() as conn:
        cursor = conn.cursor()
        for result in results_list:
            cursor.execute('''
                INSERT INTO results (roll_number, question_number, subject, score, max_score, accuracy, feedback, improvement_suggestions, semantic_match_score, keyword_match_score, structure_quality_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(roll_number).strip().lower(),
                result.get("question_number", ""),
                result.get("subject", "General"),
                result.get("score", 0.0),
                result.get("max_score", 10.0),
                result.get("accuracy", 0.0),
                result.get("feedback", ""),
                improvement_suggestions_str,
                result.get("semantic_match_score", 0.0),
                result.get("keyword_match_score", 0.0),
                result.get("structure_quality_score", 0.0)
            ))
        conn.commit()

def get_evaluation(roll_number: str) -> dict:
    """Retrieves the evaluation results and suggestions for a roll number."""
    search_key = str(roll_number).strip().lower()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT question_number, subject, score, max_score, accuracy, feedback, improvement_suggestions, semantic_match_score, keyword_match_score, structure_quality_score
            FROM results
            WHERE roll_number = ?
            ORDER BY id ASC
        ''', (search_key,))
        
        rows = cursor.fetchall()
        
        if not rows:
            return None
            
        import json
        
        # Convert sqlite3.Row objects to standard dicts matching EvaluationResult schema
        results = []
        for row in rows:
            results.append({
                "question_number": row["question_number"],
                "subject": row["subject"],
                "score": row["score"],
                "max_score": row["max_score"],
                "accuracy": row["accuracy"],
                "feedback": row["feedback"],
                "semantic_match_score": row["semantic_match_score"],
                "keyword_match_score": row["keyword_match_score"],
                "structure_quality_score": row["structure_quality_score"]
            })
            
        suggestions_str = rows[0]["improvement_suggestions"]
        try:
            suggestions_data = json.loads(suggestions_str)
            if isinstance(suggestions_data, dict):
                subject_feedback = suggestions_data.get("subject_feedback", {})
                overall_feedback = suggestions_data.get("overall_feedback", {})
                suggestions = suggestions_data.get("legacy", [])
            else:
                suggestions = suggestions_data
                subject_feedback = {}
                overall_feedback = {}
        except json.JSONDecodeError:
            suggestions = []
            subject_feedback = {}
            overall_feedback = {}
            
        return {
            "roll_number": roll_number,
            "results": results,
            "improvement_suggestions": suggestions,
            "subject_feedback": subject_feedback,
            "overall_feedback": overall_feedback
        }

def get_all_evaluations_summary() -> list:
    """Retrieves a summarized list of all evaluations grouped by roll number with subject breakdown."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                roll_number,
                subject,
                SUM(score) as subject_score,
                SUM(max_score) as subject_max,
                MAX(timestamp) as latest_evaluation
            FROM results
            GROUP BY roll_number, subject
            ORDER BY latest_evaluation DESC
        ''')
        
        rows = cursor.fetchall()
        
        students = {}
        for row in rows:
            rn = row["roll_number"]
            subj = row["subject"] if row["subject"] else "General"
            
            if rn not in students:
                students[rn] = {
                    "roll_number": rn,
                    "total_score": 0.0,
                    "total_max": 0.0,
                    "timestamp": row["latest_evaluation"],
                    "subjects": {}
                }
            
            sc = float(row["subject_score"] or 0)
            mx = float(row["subject_max"] or 0)
            
            students[rn]["total_score"] += sc
            students[rn]["total_max"] += mx
            
            students[rn]["subjects"][subj] = {
                "score": sc,
                "max": mx,
                "accuracy": round((sc/mx)*100) if mx > 0 else 0
            }
            
            if row["latest_evaluation"] > students[rn]["timestamp"]:
                students[rn]["timestamp"] = row["latest_evaluation"]
                
        summary = []
        for rn, data in students.items():
            tsc = data["total_score"]
            tmx = data["total_max"]
            data["accuracy_percentage"] = round((tsc / tmx) * 100) if tmx > 0 else 0
            summary.append(data)
            
        return sorted(summary, key=lambda x: x["timestamp"], reverse=True)

# User Authentication Helpers

def create_user(email: str, password_hash: str, role: str, roll_number: str = None):
    """Creates a new user in the database."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (email, password_hash, role, roll_number)
            VALUES (?, ?, ?, ?)
        ''', (email.lower(), password_hash, role, roll_number))
        conn.commit()
        return cursor.lastrowid

def get_user_by_email(email: str) -> dict:
    """Retrieves a user by email."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email = ?', (email.lower(),))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
