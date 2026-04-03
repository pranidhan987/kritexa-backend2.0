from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

# We will define a structured output format for the LLM
class EvaluationResult(BaseModel):
    question_number: str = Field(description="The question identifier/number")
    subject: str = Field(description="The assigned subject for this test")
    semantic_match_score: float = Field(description="Score between 0.0 and 10.0 based on purely semantic meaning alignment with the key")
    keyword_match_score: float = Field(description="Score between 0.0 and 10.0 based on using the correct important terminology")
    structure_quality_score: float = Field(description="Score between 0.0 and 10.0 based on the length, completeness, and articulation of the answer")
    score: float = Field(description="The final weighted score assigned (0.0 to max_score). Formula: (0.4 * semantic_match_score) + (0.4 * keyword_match_score) + (0.2 * structure_quality_score), scaled to max_score.")
    max_score: float = Field(description="The maximum possible score for this question according to the question paper")
    accuracy: float = Field(description="The overall accuracy percentage (0.0 to 100.0)")
    feedback: str = Field(description="Constructive feedback explaining what was correct, missing key points, incorrect concepts, or partially correct facts.")

class SubjectFeedback(BaseModel):
    well_done: List[str] = Field(description="What the student did well in this subject")
    mistakes: List[str] = Field(description="Where they made general mistakes")
    weaknesses: List[str] = Field(description="Topic-level or answer-level weaknesses")
    suggestions: List[str] = Field(description="Actionable suggestions for improvement in this subject")

class OverallFeedback(BaseModel):
    performance_summary: str = Field(description="General performance summary across the whole test")
    strengths: List[str] = Field(description="Strengths (e.g., strong in theory, weak in explanations)")
    weakness_patterns: List[str] = Field(description="Weakness patterns (e.g., low similarity in descriptive answers)")
    actionable_tips: List[str] = Field(description="Actionable improvement tips for overall test taking")

class EvaluationResponse(BaseModel):
    results: List[EvaluationResult]
    subject_feedback: SubjectFeedback = Field(description="Detailed feedback specific to the subject evaluated")
    overall_feedback: OverallFeedback = Field(description="Broader feedback regarding the student's overall performance patterns")


def evaluate_answers(questions_text: str, answer_key_text: str, student_answers_text: str, student_roll_number: str, subject: str) -> dict:
    """
    Takes the extracted texts and uses an LLM to evaluate the student answers based on the answer key.
    Uses semantic similarity rather than exact keyword matching.
    """
    # Initialize the LLM
    # Assumes OPENAI_API_KEY is in the environment
    try:
        llm = ChatOpenAI(model="gpt-4o", temperature=0)
    except Exception as e:
        # Fallback to dummy data if API key is missing during initial testing
        print("Warning: LLM Initialization failed, returning dummy evaluation data.", str(e))
        return _dummy_evaluation(student_roll_number, subject)

    # Create the evaluation prompt
    system_prompt = f"""
    You are an expert academic evaluator evaluating a {subject} test. Your task is to grade a student's descriptive answers against an answer key and question paper.
    
    CRITICAL GRADING RULE: 
    1. UNDERSTAND the meaning of the Answer Key conceptually.
    2. CHECK and UNDERSTAND the exact meaning of the Student Answer.
    3. COMPARE the student answer using three metrics:
       a) Semantic Similarity (NLP-based context meaning comparison, score out of 10)
       b) Keyword Match (presence of critical subject-specific terminology, score out of 10)
       c) Answer Structure Quality (completeness, articulation, score out of 10)
    4. SCORE: First calculate a weighted internal score out of 10 = (0.4 × semantic) + (0.4 × keyword) + (0.2 × structure). Then scale this mathematically to the maximum allocated marks (max_score) for the question.
    
    You are provided with:
    1. The original Questions
    2. The Answer Key (expected answers and max marks for each)
    3. The Student's Answers
    
    Assign a subject as "{subject}" for all questions.
    Calculate the total final accuracy percentage (0-100) per question.
    Provide highly specific feedback highlighting missing key points, incorrect concepts, or partially correct answers.
    Generate detailed Subject-wise feedback indicating their topic-level weaknesses and well-done points.
    Generate Overall feedback showcasing their weakness patterns and taking-strategy strengths/weaknesses.
    """
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Questions:\n{{questions}}\n\nAnswer Key:\n{{answer_key}}\n\nStudent Answers:\n{{student_answers}}")
    ])
    
    # Format the chain to output structured data
    structured_llm = llm.with_structured_output(EvaluationResponse)
    
    # Combine prompt and LLM
    chain = prompt | structured_llm
    
    try:
        response = chain.invoke({
            "questions": questions_text,
            "answer_key": answer_key_text,
            "student_answers": student_answers_text
        })
        
        # Convert Pydantic models to dict for the API response
        response_dict = response.model_dump()
        # Inject the manual roll number
        response_dict["roll_number"] = student_roll_number
        return response_dict
        
    except Exception as e:
        print(f"Error during LLM evaluation: {e}")
        return _dummy_evaluation(student_roll_number, subject)

def _dummy_evaluation(student_roll_number: str, subject: str) -> dict:
    """Fallback method for testing without API keys."""
    return {
        "roll_number": student_roll_number,
        "subject_feedback": {
            "well_done": ["Clear handwriting", "Attempted all questions"],
            "mistakes": ["Missed some key definitions"],
            "weaknesses": ["Core theoretical concepts"],
            "suggestions": ["Include definitions when answering theory questions.", "Provide examples to strengthen explanations."]
        },
        "overall_feedback": {
            "performance_summary": "Average performance with room to improve theory.",
            "strengths": ["Answering structure"],
            "weakness_patterns": ["Missing terminology"],
            "actionable_tips": ["Focus on core concepts instead of memorizing."]
        },
        "results": [
            {
                "question_number": "Q1",
                "subject": subject,
                "semantic_match_score": 9.0,
                "keyword_match_score": 8.0,
                "structure_quality_score": 8.5,
                "score": 8.5,
                "max_score": 10.0,
                "accuracy": 85.0,
                "feedback": "Good conceptual explanation but missing one key definition."
            },
            {
                "question_number": "Q2",
                "subject": subject,
                "semantic_match_score": 4.0,
                "keyword_match_score": 4.0,
                "structure_quality_score": 6.0,
                "score": 4.0,
                "max_score": 10.0,
                "accuracy": 40.0,
                "feedback": "Answer is partially correct. Missing terminology."
            }
        ]
    }
