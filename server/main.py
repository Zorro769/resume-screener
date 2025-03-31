import os
import json
import re
from datetime import datetime
import fitz
import docx
from flask import Flask, render_template, request, jsonify, redirect, url_for
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from werkzeug.utils import secure_filename
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Paths to JSON files
VACANCIES_JSON = "json_data/vacancies.json"
RESUMES_JSON = "json_data/resumes.json"

# Database configuration
engine = create_engine('sqlite:///jobs.db', echo=True)
Base = declarative_base()
Session = sessionmaker(bind=engine)

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {'pdf', 'docx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini_model = None
if not GEMINI_API_KEY:
    print("Warning: GEMINI_API_KEY not found in environment variables.")
else:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel('gemini-pro')
        print("Gemini API configured successfully.")
    except Exception as e:
        print(f"Error configuring Gemini API: {e}")

# Vacancy model
class Vacancy(Base):
    __tablename__ = 'vacancies'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    requirements = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

# Resume model
class Resume(Base):
    __tablename__ = 'resumes'
    
    id = Column(Integer, primary_key=True)
    filename = Column(String, nullable=False)
    full_name = Column(String)
    email = Column(String)
    phone = Column(String)
    education = Column(Text)
    skills = Column(Text)
    experience = Column(Text)
    content = Column(Text)

# Create database tables
Base.metadata.create_all(engine)

def save_json(filepath, data):
    """Save data to a JSON file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def extract_text(file_path):
    text = ""
    try:
        if file_path.lower().endswith(".pdf"):
            with fitz.open(file_path) as doc:
                for page in doc:
                    text += page.get_text("text") + "\n"
        elif file_path.lower().endswith(".docx"):
            doc = docx.Document(file_path)
            text = "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        print(f"Error extracting text from {file_path}: {e}")
        return ""
    return text.strip()

def extract_resume_data(text):
    data = {
        "full_name": "Not found",
        "email": "Not found",
        "phone": "Not found",
        "education": "Not found",
        "skills": "Not found",
        "experience": "Not found",
    }
    lines = text.split("\n")

    # Extract full name (assumes first line is name)
    if lines:
        name_match = re.search(r"^([A-Z][a-z]+\s+){1,2}[A-Z][a-z]+", lines[0])
        if name_match:
             data["full_name"] = name_match.group(0).strip()
        elif len(lines[0].split()) <= 4:
            data["full_name"] = lines[0].strip()

    # Extract email
    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    if email_match:
        data["email"] = email_match.group(0)
    else: # Explicitly set to "Not found" if regex fails
        data["email"] = "Not found"


    # Extract phone number
    phone_match = re.search(r"(?:(?:\+?\d{1,3})?[- .(]*?)?(?:\d{3})?[- .)]*?\d{3}[- .]?\d{4}|\d{10,11})", text)
    if phone_match:
        phone_digits = re.sub(r'\D', '', phone_match.group(0))
        if len(phone_digits) >= 10:
             data["phone"] = phone_match.group(0).strip()
        else:
             data["phone"] = "Not found"
    else:
        data["phone"] = "Not found"


    # Extract education
    education_section = re.search(r"(Education|Academic Background)[:\n](.*?)(?=\n[A-Z]|$)", text, re.IGNORECASE | re.DOTALL)
    if education_section:
        data["education"] = education_section.group(2).strip()
    else:
        data["education"] = "Not found"


    # Extract skills
    skills_section = re.search(r"(Skills|Core Competencies|Technical Skills)[:\n](.*?)(?=\n[A-Z]|$)", text, re.IGNORECASE | re.DOTALL)
    if skills_section:
        data["skills"] = skills_section.group(2).strip()
    else:
         common_skills = re.findall(r"(Python|Java|SQL|JavaScript|React|Angular|Vue|Docker|Kubernetes|Git|Linux|AWS|Azure|GCP)", text, re.IGNORECASE)
         if common_skills:
             data["skills"] = ", ".join(list(set(common_skills)))
         else:
            data["skills"] = "Not found"


    # Extract experience
    experience_section = re.search(r"(Experience|Work Experience|Employment History)[:\n](.*?)(?=\n[A-Z]|$)", text, re.IGNORECASE | re.DOTALL)
    if experience_section:
        data["experience"] = experience_section.group(2).strip()
    else:
        data["experience"] = "Not found"

    return data


@app.route('/')
def home():
    message = request.args.get('message')
    return render_template('home.html', message=message)

@app.route('/create_vacancy', methods=['GET', 'POST'])
def create_vacancy():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        requirements = request.form.get('requirements')

        if not title:
            return "Vacancy title cannot be empty", 400

        session = Session()
        try:
            vacancy = Vacancy(title=title, description=description, requirements=requirements)
            session.add(vacancy)
            session.commit()

            # Update JSON file with vacancies
            vacancies = session.query(Vacancy).all()
            save_json(VACANCIES_JSON, [
                {
                    "id": v.id,
                    "title": v.title,
                    "description": v.description,
                    "requirements": v.requirements,
                    "created_at": v.created_at.strftime("%Y-%m-%d %H:%M:%S") if v.created_at else None
                } for v in vacancies
            ])
            session.refresh(vacancy) # Refresh to get ID generated by DB
            print(f"Created Vacancy ID: {vacancy.id}")
            return redirect(url_for('vacancy_list'))
        except Exception as e:
            session.rollback()
            print(f"Error saving vacancy: {e}")
            return "An error occurred while creating the vacancy", 500
        finally:
            session.close()

    return render_template('create_vacancy.html')

@app.route('/vacancies', methods=['GET'])
def vacancy_list():
    session = Session()
    vacancies = session.query(Vacancy).order_by(Vacancy.created_at.desc()).all()
    session.close()
    return render_template('vacancy_list.html', vacancies=vacancies)

# Return vacancies in JSON format
@app.route('/api/vacancies', methods=['GET'])
def get_vacancies_json():
    session = Session()
    vacancies = session.query(Vacancy).order_by(Vacancy.created_at.desc()).all()
    session.close()
    return jsonify([
        {
            "id": v.id,
            "title": v.title,
            "description": v.description,
            "requirements": v.requirements,
            "created_at": v.created_at.strftime("%Y-%m-%d %H:%M:%S") if v.created_at else None
        } for v in vacancies
    ])

# Resume file upload and text extraction
@app.route('/upload', methods=['POST'])
def upload_resume():
    if 'file' not in request.files:
        return "No file part in the request", 400
    file = request.files['file']

    if file.filename == '':
        return "No file selected", 400

    if file and '.' in file.filename and \
       file.filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS:
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        secure_name = f"{timestamp}_{filename}" # Use timestamped name
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_name)

        try:
            file.save(filepath)
            print(f"File saved: {filepath}")

            # Extract text and resume details
            resume_text = extract_text(filepath)
            if not resume_text:
                 print(f"Failed to extract text from file: {secure_name}")
                 # Consider removing the empty file?
                 # if os.path.exists(filepath): os.remove(filepath)
                 return "Failed to process the resume file", 500

            resume_data = extract_resume_data(resume_text)
            print(f"Extracted data: {resume_data}")

            session = Session()
            try:
                resume = Resume(
                    filename=secure_name,
                    full_name=resume_data.get("full_name", "Not found"),
                    email=resume_data.get("email", "Not found"),
                    phone=resume_data.get("phone", "Not found"),
                    education=resume_data.get("education", "Not found"),
                    skills=resume_data.get("skills", "Not found"),
                    experience=resume_data.get("experience", "Not found"),
                    content=resume_text
                )
                session.add(resume)
                session.commit()
                print(f"Resume ID {resume.id} added to DB.")

                # Update JSON file with resumes
                resumes = session.query(Resume).all()
                save_json(RESUMES_JSON, [
                   {
                       "id": r.id,
                       "filename": r.filename,
                       "full_name": r.full_name,
                       "email": r.email,
                       "phone": r.phone,
                       "education": r.education, # This will reflect the parsed value
                       "skills": r.skills,
                       "experience": r.experience
                   } for r in resumes
                ])

            except Exception as db_err:
                session.rollback()
                print(f"Error saving resume to DB: {db_err}")
                return "Error saving resume data", 500
            finally:
                session.close()

            return redirect(url_for('home', message="Resume uploaded successfully"))

        except Exception as e:
            print(f"Error processing file {filename}: {e}")
            if os.path.exists(filepath):
                 try:
                     os.remove(filepath)
                     print(f"Cleaned up file: {filepath}")
                 except OSError as remove_err:
                     print(f"Failed to delete file {filepath}: {remove_err}")
            return f"An error occurred during file upload: {e}", 500
    else:
        return f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}", 400

# Return resumes in JSON format
@app.route('/api/resumes', methods=['GET'])
def get_resumes_json():
    session = Session()
    resumes = session.query(Resume).all()
    session.close()
    return jsonify([
        {
            "id": r.id,
            "filename": r.filename,
            "full_name": r.full_name,
            "email": r.email,
            "phone": r.phone,
            "education": r.education,
            "skills": r.skills,
            "experience": r.experience
        } for r in resumes
    ])

#filter function
@app.route('/api/filter_candidates/<int:vacancy_id>', methods=['GET'])
def filter_candidates_by_vacancy(vacancy_id):
    session = Session()
    try:
        vacancy = session.query(Vacancy).filter_by(id=vacancy_id).first()
        if not vacancy:
            return jsonify({"error": "Vacancy not found"}), 404

        if not vacancy.requirements:
             return jsonify({"error": "Vacancy has no specified requirements"}), 400

        required_skills_list = [skill.strip().lower() for skill in re.split(r'[,\s\n]+', vacancy.requirements) if skill.strip()]
        if not required_skills_list:
             return jsonify({"warning": "Could not extract keywords from vacancy requirements"}), 200

        print(f"Required skills for vacancy {vacancy_id}: {required_skills_list}")

        all_resumes = session.query(Resume).all()

        filtered_candidates = []
        for resume in all_resumes:
            text_to_search = ""
            if resume.skills:
                text_to_search += resume.skills.lower() + " "
            if resume.content:
                text_to_search += resume.content.lower()

            if not text_to_search:
                continue

            found_skills_count = 0
            matched_skill_example = None
            for req_skill in required_skills_list:
                if re.search(r'\b' + re.escape(req_skill) + r'\b', text_to_search):
                    found_skills_count += 1
                    matched_skill_example = req_skill
                    break

            if found_skills_count > 0:
                 filtered_candidates.append({
                      "id": resume.id,
                      "filename": resume.filename,
                      "full_name": resume.full_name,
                      "email": resume.email,
                      "phone": resume.phone,
                      "matched_skills_approx": matched_skill_example
                 })

        print(f"Found {len(filtered_candidates)} candidates for vacancy {vacancy_id}")
        return jsonify(filtered_candidates)

    except Exception as e:
        # Ensure session is closed in case of error before returning
        if session.is_active:
             session.close()
        print(f"Error filtering candidates for vacancy {vacancy_id}: {e}")
        return jsonify({"error": "Internal server error during filtering"}), 500
    finally:
        # Final check to ensure session closure
         if session.is_active:
              session.close()

#GEMINI recommendation
@app.route('/api/best_candidate/<int:vacancy_id>', methods=['GET'])
def get_best_candidate_gemini(vacancy_id):
    if not GEMINI_API_KEY or not gemini_model:
        return jsonify({"error": "Gemini API is not configured or failed to initialize"}), 503

    session = Session()
    try:
        vacancy = session.query(Vacancy).filter_by(id=vacancy_id).first()
        if not vacancy:
            return jsonify({"error": "Vacancy not found"}), 404

        all_resumes = session.query(Resume).all()
        if not all_resumes:
             return jsonify({"message": "No resumes available for analysis"}), 200

        vacancy_details = f"Vacancy: {vacancy.title}\nDescription: {vacancy.description}\nRequirements: {vacancy.requirements}\n\n"

        resumes_text = ""
        resume_map = {}
        for i, resume in enumerate(all_resumes):
             resume_id_tag = f"RESUME_ID_{resume.id}"
             resumes_text += f"--- Candidate {resume_id_tag} ---\n"
             if resume.full_name and resume.full_name != "Not found":
                 resumes_text += f"Name: {resume.full_name}\n"
             if resume.content:
                 resumes_text += f"Resume Text:\n{resume.content}\n\n"
             else:
                  resumes_text += "Resume Text: [Not Available]\n\n"
             resume_map[resume_id_tag] = resume

        prompt = (
            f"{vacancy_details}"
            "Analyze the following candidate resumes:\n\n"
            f"{resumes_text}"
            "Task: Select the SINGLE MOST SUITABLE candidate for this vacancy. "
            "Briefly justify your choice, highlighting key matches with the requirements. "
            "In your response, first state the identifier of the best candidate in the format 'Best Candidate: RESUME_ID_XXX', "
            "then provide the justification."
        )

        try:
            print(f"Sending request to Gemini API for vacancy {vacancy_id}...")
            response = gemini_model.generate_content(prompt)
            print(f"Received response from Gemini API.")

            match = re.search(r"Best Candidate: (RESUME_ID_\d+)", response.text, re.IGNORECASE)
            if match:
                best_candidate_tag = match.group(1).upper()
                best_candidate_resume = resume_map.get(best_candidate_tag)

                if best_candidate_resume:
                    # Session closed in finally block
                    return jsonify({
                        "best_candidate": {
                            "id": best_candidate_resume.id,
                            "filename": best_candidate_resume.filename,
                            "full_name": best_candidate_resume.full_name,
                            "email": best_candidate_resume.email,
                            "phone": best_candidate_resume.phone,
                            "skills": best_candidate_resume.skills,
                            "experience": best_candidate_resume.experience
                        },
                        "gemini_analysis": response.text
                    })
                else:
                    print(f"Error: Gemini returned ID {best_candidate_tag}, but no resume with this ID was found in the map.")
                    return jsonify({"error": f"Error matching Gemini response: Could not find resume for {best_candidate_tag}", "gemini_response": response.text}), 500
            else:
                print("Error: Could not extract the best candidate ID from the Gemini response.")
                return jsonify({"error": "Could not determine the best candidate from the Gemini response", "gemini_response": response.text}), 500

        except Exception as gemini_err:
             print(f"Error calling Gemini API: {gemini_err}")
             # Session closed in finally block
             return jsonify({"error": f"Error interacting with Gemini API: {gemini_err}"}), 500

    except Exception as e:
        import traceback
        print(f"Error in endpoint /api/best_candidate/{vacancy_id}:\n{traceback.format_exc()}")
        # Session closed in finally block
        return jsonify({"error": "Internal server error"}), 500
    finally:
        # Ensure session is always closed
        if session.is_active:
            session.close()


if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
        print(f"Created upload folder: {UPLOAD_FOLDER}")
    app.run(debug=True)