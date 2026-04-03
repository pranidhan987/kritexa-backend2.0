import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_flow():
    print("Testing Auth and Evaluation Flow...")
    
    # 1. Signup Teacher
    print("\n--- 1. Signing up Teacher ---")
    teacher_payload = {
        "email": "teacher@test.com",
        "password": "password123",
        "role": "teacher"
    }
    r = requests.post(f"{BASE_URL}/signup", json=teacher_payload)
    if r.status_code != 200:
        print("Teacher Signup failed:", r.status_code, r.text)
        return
    print("Teacher Signup:", r.status_code, r.json())
    teacher_token = r.json().get("access_token")

    # 2. Signup Student
    print("\n--- 2. Signing up Student ---")
    student_payload = {
        "email": "student1@test.com",
        "password": "password123",
        "role": "student",
        "roll_number": "1001"
    }
    r = requests.post(f"{BASE_URL}/signup", json=student_payload)
    if r.status_code != 200:
        print("Student Signup failed:", r.status_code, r.text)
        return
    print("Student Signup:", r.status_code, r.json())
    student_token = r.json().get("access_token")

    # 3. Teacher evaluates a submission
    print("\n--- 3. Teacher Evaluates Submission ---")
    # Generating dummy PDFs in memory
    try:
        from reportlab.pdfgen import canvas
        import io
        
        def create_dummy_pdf(text):
            buffer = io.BytesIO()
            c = canvas.Canvas(buffer)
            c.drawString(100, 750, text)
            c.save()
            buffer.seek(0)
            return buffer.read()
            
        q_pdf = create_dummy_pdf("Q1: Explain photosynthesis. Marks: 5")
        k_pdf = create_dummy_pdf("A1: Process by which plants use sunlight to synthesize food from CO2 and water. Max Marks: 5.")
        s_pdf = create_dummy_pdf("Roll Number: 1001. A1: Plants make food using structural sunlight.")
        
        files = {
            "questions": ("q.pdf", q_pdf, "application/pdf"),
            "answer_key": ("k.pdf", k_pdf, "application/pdf"),
            "student_answers": ("s.pdf", s_pdf, "application/pdf"),
        }
        
        headers = {"Authorization": f"Bearer {teacher_token}"}
        r = requests.post(f"{BASE_URL}/evaluate", files=files, headers=headers)
        print("Evaluation Status:", r.status_code)
        if r.status_code == 200:
            payload = r.json()
            print("Evaluation Payload:", payload)
            extracted_roll = payload.get("roll_number")
            print("Extracted Roll Number:", extracted_roll)
        else:
            print(r.text)
    except Exception as e:
        print("Could not generate or send PDFs:", e)

    # 4. Student gets result
    if extracted_roll:
        print(f"\n--- 4. Student Gets Results for {extracted_roll} ---")
        headers = {"Authorization": f"Bearer {student_token}"}
        r = requests.get(f"{BASE_URL}/result/{extracted_roll}", headers=headers)
        print("Student Result Status:", r.status_code)
        try:
            data = r.json()
            print("Suggestions:", data.get("improvement_suggestions"))
        except:
            pass

    # 5. Teacher gets all results
    print("\n--- 5. Teacher Gets All Results ---")
    headers = {"Authorization": f"Bearer {teacher_token}"}
    r = requests.get(f"{BASE_URL}/results", headers=headers)
    print("All Results Status:", r.status_code)
    if r.status_code == 200:
        print("Total records:", len(r.json()["results"]))

if __name__ == "__main__":
    test_flow()
