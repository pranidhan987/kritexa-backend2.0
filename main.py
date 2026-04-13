from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List, Optional
import uvicorn
import os
from datetime import datetime, timedelta
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel

from services.pdf_service import extract_text_from_pdf
from services.evaluation_service import evaluate_answers
from database import init_db, save_evaluation, get_evaluation, get_all_evaluations_summary, create_user, get_user_by_email

app = FastAPI(title="Kritexa API", description="AI-based answer evaluation platform")

# Initialize SQLite database
init_db()

# Configure CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/status")
def read_root():
    return {"message": "Kritexa API is running"}

# --- AUTHENTICATION SETUP --- #
SECRET_KEY = "super_secret_kritexa_key" # In production, use env var
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def verify_password(plain_password: str, hashed_password: str):
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password: str):
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user_by_email(email)
    if user is None:
        raise credentials_exception
    return user

# --- SCHEMAS --- #
class UserCreate(BaseModel):
    email: str
    password: str
    role: str # 'teacher' or 'student'
    roll_number: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    roll_number: Optional[str] = None

# --- AUTH ROUTES --- #
@app.post("/signup", response_model=Token)
async def signup(user: UserCreate):
    try:
        existing_user = get_user_by_email(user.email)
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")
            
        hashed_password = get_password_hash(user.password)
        create_user(user.email, hashed_password, user.role, user.roll_number)
            
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.email, "role": user.role}, expires_delta=access_token_expires
        )
        return {"access_token": access_token, "token_type": "bearer", "role": user.role, "roll_number": user.roll_number}
    except Exception as e:
        import traceback
        with open("full_error.log", "a") as f:
            f.write(f"Signup error: {e}\n")
            f.write(traceback.format_exc() + "\n")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = get_user_by_email(form_data.username)
    if (not user) or (not verify_password(form_data.password, user['password_hash'])):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user['email'], "role": user['role']}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "role": user['role'], "roll_number": user['roll_number']}

# --- MAIN API ROUTES --- #
@app.post("/evaluate")
async def evaluate_submission(
    student_roll_number: str = Form(...),
    subject: str = Form(...),
    questions: UploadFile = File(...),
    answer_key: UploadFile = File(...),
    student_answers: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    if current_user['role'] != 'teacher':
        raise HTTPException(status_code=403, detail="Only teachers can evaluate submissions")
    try:
        # 1. Read PDF files into memory
        questions_bytes = await questions.read()
        answer_key_bytes = await answer_key.read()
        student_answers_bytes = await student_answers.read()
        
        # 2. Extract text from PDFs
        questions_text = extract_text_from_pdf(questions_bytes)
        answer_key_text = extract_text_from_pdf(answer_key_bytes)
        student_answers_text = extract_text_from_pdf(student_answers_bytes)
        
        # 3. Evaluate semantically
        evaluation_data = evaluate_answers(questions_text, answer_key_text, student_answers_text, student_roll_number, subject)
        
        # 4. Store in SQLite DB by roll number
        roll_number = evaluation_data.get("roll_number", "UNKNOWN")
        save_evaluation(roll_number, evaluation_data)
        
        return {
            "status": "success",
            "roll_number": roll_number,
            "results": evaluation_data
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/result/{roll_number}")
async def get_evaluation_result(roll_number: str):
    # Lookup in our SQLite DB
    evaluation_data = get_evaluation(roll_number)
    
    if evaluation_data:
        return {
            "status": "success",
            "roll_number": roll_number,
            "results": evaluation_data["results"],
            "improvement_suggestions": evaluation_data.get("improvement_suggestions", [])
        }
    else:
        raise HTTPException(status_code=404, detail="Result not found for the provided roll number")

@app.get("/results")
async def get_all_results(current_user: dict = Depends(get_current_user)):
    """Returns a summary of all evaluated answers."""
    if current_user['role'] != 'teacher':
        raise HTTPException(status_code=403, detail="Only teachers can view all results")
    summary = get_all_evaluations_summary()
    return {
        "status": "success",
        "results": summary
    }

# Serve frontend static assets
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
frontend_assets = os.path.join(frontend_dist, "assets")

if os.path.exists(frontend_assets):
    app.mount("/assets", StaticFiles(directory=frontend_assets), name="assets")

@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    file_path = os.path.join(frontend_dist, full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    index_path = os.path.join(frontend_dist, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Frontend not built yet."}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
