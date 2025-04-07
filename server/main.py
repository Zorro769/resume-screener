import os
import json
import re
from datetime import datetime
import fitz # PyMuPDF
import docx
from flask import Flask, request, jsonify
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import sessionmaker, relationship, joinedload
from sqlalchemy.ext.declarative import declarative_base
from werkzeug.utils import secure_filename
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Paths to JSON
VACANCIES_JSON = "json_data/vacancies.json"
RESUMES_JSON = "json_data/resumes.json"

# Database configuration
engine = create_engine('sqlite:///jobs.db', echo=False)
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
        # Using a specific model known to be available and suitable
        gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        print("Gemini API configured successfully.")
    except Exception as e:
        print(f"Error configuring Gemini API: {e}")
        gemini_model = None # Ensure model is None if config fails

# Association Table Model
class Application(Base):
    __tablename__ = 'applications'
    id = Column(Integer, primary_key=True)
    vacancy_id = Column(Integer, ForeignKey('vacancies.id', ondelete='CASCADE'), nullable=False)
    resume_id = Column(Integer, ForeignKey('resumes.id', ondelete='CASCADE'), nullable=False)
    applied_at = Column(DateTime, default=datetime.utcnow)
    # Prevent duplicate applications for the same resume to the same vacancy
    __table_args__ = (UniqueConstraint('vacancy_id', 'resume_id', name='_vacancy_resume_uc'),)

# Vacancy model
class Vacancy(Base):
    __tablename__ = 'vacancies'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    requirements = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship to link Vacancies to Applications
    applications = relationship("Application", back_populates="vacancy", cascade="all, delete-orphan")

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
    content = Column(Text) # Keep the full extracted text

    # Relationship to link Resumes to Applications
    applications = relationship("Application", back_populates="resume", cascade="all, delete-orphan")

Application.vacancy = relationship("Vacancy", back_populates="applications")
Application.resume = relationship("Resume", back_populates="applications")


# Create database tables
Base.metadata.create_all(engine)

def save_json(filepath, data):
    """Save data to a JSON file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Error saving JSON to {filepath}: {e}")


def extract_text(file_path):
    """Extract text from PDF or DOCX file."""
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
        return "" # Return empty string on error
    return text.strip()


def extract_resume_data(text):
    """Extract structured data from resume text using regex."""
    data = {
        "full_name": "Not found",
        "email": "Not found",
        "phone": "Not found",
        "education": "Not found",
        "skills": "Not found",
        "experience": "Not found",
    }
    if not text:
        return data

    lines = text.split("\n")

    # Extract full name
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
    else: 
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

# Create Vacancy 
@app.route('/api/vacancies', methods=['POST'])
def create_vacancy_api():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    title = data.get('title')
    description = data.get('description')
    requirements = data.get('requirements')

    if not title:
        return jsonify({"error": "Vacancy title cannot be empty"}), 400

    session = Session()
    try:
        vacancy = Vacancy(title=title, description=description, requirements=requirements)
        session.add(vacancy)
        session.commit()
        session.refresh(vacancy) # Get the generated ID and timestamp

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

        print(f"Created Vacancy ID: {vacancy.id}")
        return jsonify({
            "message": "Vacancy created successfully",
            "vacancy": {
                "id": vacancy.id,
                "title": vacancy.title,
                "description": vacancy.description,
                "requirements": vacancy.requirements,
                "created_at": vacancy.created_at.isoformat() if vacancy.created_at else None
            }
        }), 201 # HTTP 201 Created
    except Exception as e:
        session.rollback()
        print(f"Error saving vacancy: {e}")
        return jsonify({"error": "An error occurred while creating the vacancy"}), 500
    finally:
        session.close()


# Return vacancies in JSON format
@app.route('/api/vacancies', methods=['GET'])
def get_vacancies_json():
    session = Session()
    try:
        vacancies = session.query(Vacancy).order_by(Vacancy.created_at.desc()).all()
        return jsonify([
            {
                "id": v.id,
                "title": v.title,
                "description": v.description,
                "requirements": v.requirements,
                "created_at": v.created_at.strftime("%Y-%m-%d %H:%M:%S") if v.created_at else None
            } for v in vacancies
        ])
    except Exception as e:
        print(f"Error fetching vacancies: {e}")
        return jsonify({"error": "Failed to retrieve vacancies"}), 500
    finally:
        session.close()

# Get Specific Vacancy Details (including applicants)
@app.route('/api/vacancies/<int:vacancy_id>', methods=['GET'])
def get_vacancy_detail_api(vacancy_id):
    session = Session()
    try:
        vacancy = session.query(Vacancy).options(
            joinedload(Vacancy.applications).joinedload(Application.resume)
        ).filter(Vacancy.id == vacancy_id).first()

        if not vacancy:
            return jsonify({"error": f"Vacancy with ID {vacancy_id} not found"}), 404

        applicants_data = []
        for app in vacancy.applications:
            if app.resume:
                applicants_data.append({
                    "resume_id": app.resume.id,
                    "full_name": app.resume.full_name,
                    "email": app.resume.email,
                    "phone": app.resume.phone,
                    "filename": app.resume.filename,
                    "applied_at": app.applied_at.strftime("%Y-%m-%d %H:%M:%S") if app.applied_at else None
                })

        return jsonify({
            "id": vacancy.id,
            "title": vacancy.title,
            "description": vacancy.description,
            "requirements": vacancy.requirements,
            "created_at": vacancy.created_at.strftime("%Y-%m-%d %H:%M:%S") if vacancy.created_at else None,
            "applicants": sorted(applicants_data, key=lambda x: x.get('full_name') or '') # Sort applicants by name
        })
    except Exception as e:
        print(f"Error fetching vacancy details for ID {vacancy_id}: {e}")
        return jsonify({"error": "Internal server error fetching vacancy details"}), 500
    finally:
        session.close()


@app.route('/api/vacancies/<int:vacancy_id>/apply', methods=['POST'])
def upload_resume_api(vacancy_id):
    session = Session()
    filepath = None
    try:
        # Check if vacancy exists first
        vacancy = session.query(Vacancy).filter_by(id=vacancy_id).first()
        if not vacancy:
            return jsonify({"error": f"Vacancy with ID {vacancy_id} not found"}), 404

        if 'file' not in request.files:
            return jsonify({"error": "No file part in the request"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400

        if file and '.' in file.filename and \
           file.filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS:
            original_filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            secure_name = f"{timestamp}_{original_filename}" # Use timestamped name
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_name)

            try:
                file.save(filepath)
                print(f"File saved: {filepath}")

                # Extract text and resume details
                resume_text = extract_text(filepath)
                if not resume_text:
                     print(f"Failed to extract text from file: {secure_name}")
                     if os.path.exists(filepath): os.remove(filepath)
                     return jsonify({"error": "Failed to process the resume file (could not extract text)"}), 500


                resume_data = extract_resume_data(resume_text)
                print(f"Extracted data: {resume_data}")


                # Create the Resume record
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
                session.flush() # Assigns an ID to the resume object

                # Check if this resume is already linked to this vacancy
                existing_application = session.query(Application).filter_by(
                    vacancy_id=vacancy_id,
                    resume_id=resume.id
                ).first()

                application_created = False
                if not existing_application:
                    application = Application(vacancy_id=vacancy_id, resume_id=resume.id)
                    session.add(application)
                    application_created = True

                session.commit() # Commit resume and potentially application

                if application_created:
                    print(f"Resume ID {resume.id} created and linked to Vacancy ID {vacancy_id}.")
                    message = "Resume uploaded and application submitted successfully"
                    status_code = 201
                else:
                    print(f"Resume ID {resume.id} already applied to Vacancy ID {vacancy_id}.")
                    message = "This resume was already submitted for this vacancy"
                    status_code = 200 # OK, but not created

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

                return jsonify({
                    "message": message,
                    "resume_id": resume.id,
                    "vacancy_id": vacancy_id,
                    "filename": secure_name
                }), status_code

            except Exception as e:
                session.rollback() 
                error_filename = original_filename if 'original_filename' in locals() else secure_name
                print(f"Error processing file {error_filename} or saving to DB: {e}")
                # Clean up uploaded file if saving failed
                if filepath and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                        print(f"Cleaned up file: {filepath}")
                    except OSError as remove_err:
                        print(f"Failed to delete file {filepath}: {remove_err}")
                return jsonify({"error": f"An error occurred during file processing or saving: {e}"}), 500

        else:
            return jsonify({"error": f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"}), 400

    finally:
        # Ensure session is always closed
        if session.is_active:
            session.close()


# Return resumes in JSON format
@app.route('/api/resumes', methods=['GET'])
def get_resumes_json():
    session = Session()
    try:
        resumes = session.query(Resume).options(
            joinedload(Resume.applications)
        ).all()

        resumes_data = []
        for r in resumes:
            applied_vacancy_ids = [app.vacancy_id for app in r.applications]
            resumes_data.append({
                "id": r.id,
                "filename": r.filename,
                "full_name": r.full_name,
                "email": r.email,
                "phone": r.phone,
                "education": r.education,
                "skills": r.skills,
                "experience": r.experience,
                "applied_vacancy_ids": applied_vacancy_ids # Include IDs of vacancies applied to
            })
        return jsonify(resumes_data)
    except Exception as e:
        print(f"Error fetching resumes: {e}")
        return jsonify({"error": "Failed to retrieve resumes"}), 500
    finally:
        session.close()

# Get Specific Resume Details
@app.route('/api/resumes/<int:resume_id>', methods=['GET'])
def get_resume_detail_api(resume_id):
    session = Session()
    try:
        resume = session.query(Resume).options(
            joinedload(Resume.applications).joinedload(Application.vacancy) # Eager load applications and related vacancies
        ).filter(Resume.id == resume_id).first()

        if not resume:
            return jsonify({"error": f"Resume with ID {resume_id} not found"}), 404

        applied_vacancies_data = []
        for app in resume.applications:
            if app.vacancy:
                applied_vacancies_data.append({
                    "vacancy_id": app.vacancy.id,
                    "title": app.vacancy.title,
                    "applied_at": app.applied_at.strftime("%Y-%m-%d %H:%M:%S") if app.applied_at else None
                })

        return jsonify({
            "id": resume.id,
            "filename": resume.filename,
            "full_name": resume.full_name,
            "email": resume.email,
            "phone": resume.phone,
            "education": resume.education,
            "skills": resume.skills,
            "experience": resume.experience,
            "applied_to_vacancies": sorted(applied_vacancies_data, key=lambda x: x.get('applied_at') or '', reverse=True) # Sort by application date
        })
    except Exception as e:
        print(f"Error fetching resume details for ID {resume_id}: {e}")
        return jsonify({"error": "Internal server error fetching resume details"}), 500
    finally:
        session.close()


@app.route('/api/filter_candidates/<int:vacancy_id>', methods=['GET'])
def filter_candidates_by_vacancy(vacancy_id):
    session = Session()
    try:
        # Fetch vacancy and eagerly load its applications and the associated resumes
        vacancy = session.query(Vacancy).options(
            joinedload(Vacancy.applications).joinedload(Application.resume)
        ).filter(Vacancy.id == vacancy_id).first()

        if not vacancy:
            return jsonify({"error": "Vacancy not found"}), 404

        if not vacancy.requirements:
            return jsonify({"warning": "Vacancy has no specified requirements for filtering"}), 200

        required_skills_list = [skill.strip().lower() for skill in re.split(r'[,\s\n]+', vacancy.requirements) if skill.strip()]
        if not required_skills_list:
            return jsonify({"warning": "Could not extract keywords from vacancy requirements"}), 200

        print(f"Required skills for vacancy {vacancy_id}: {required_skills_list}")

        # Get resumes ONLY from the applications linked to this vacancy
        applied_resumes = [app.resume for app in vacancy.applications if app.resume]

        if not applied_resumes:
             return jsonify({"message": f"No candidates found for vacancy {vacancy_id}"}), 200

        filtered_candidates = []
        for resume in applied_resumes: # Iterate through linked resumes only
            text_to_search = (resume.skills or "").lower() + " " + (resume.content or "").lower()

            if not text_to_search.strip():
                continue

            found_skills_count = 0
            matched_skill_example = None
            for req_skill in required_skills_list:
                if re.search(r'\b' + re.escape(req_skill) + r'\b', text_to_search):
                    found_skills_count += 1
                    matched_skill_example = req_skill
                    break # Stop after first match as per original logic

            if found_skills_count > 0:
                filtered_candidates.append({
                    "id": resume.id,
                    "filename": resume.filename,
                    "full_name": resume.full_name,
                    "email": resume.email,
                    "phone": resume.phone,
                    "matched_skills_approx": matched_skill_example
                })

        print(f"Found {len(filtered_candidates)} candidates matching criteria for vacancy {vacancy_id}")
        return jsonify({
            "vacancy_id": vacancy_id,
            "vacancy_title": vacancy.title, # Added title for context
            "candidates": filtered_candidates
            })

    except Exception as e:
        print(f"Error filtering candidates for vacancy {vacancy_id}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Internal server error during filtering"}), 500
    finally:
        if session.is_active:
            session.close()



@app.route('/api/best_candidate/<int:vacancy_id>', methods=['GET'])
def get_best_candidate_gemini(vacancy_id):
    if not GEMINI_API_KEY or not gemini_model:
        return jsonify({"error": "Gemini API is not configured or failed to initialize"}), 503

    session = Session()
    try:
        vacancy = session.query(Vacancy).options(
            joinedload(Vacancy.applications).joinedload(Application.resume)
        ).filter(Vacancy.id == vacancy_id).first()

        if not vacancy:
            return jsonify({"error": "Vacancy not found"}), 404

        # Get resumes ONLY from the applications linked to this vacancy
        applied_resumes = [app.resume for app in vacancy.applications if app.resume]

        if not applied_resumes:
             # Changed message slightly
             return jsonify({"message": f"No candidates have applied to vacancy {vacancy_id} to analyze"}), 200

        vacancy_details = f"Vacancy ID: {vacancy.id}\nVacancy Title: {vacancy.title}\nDescription: {vacancy.description}\nRequirements: {vacancy.requirements}\n\n"

        resumes_text = ""
        resume_map = {}
        # Iterate through linked resumes only
        for i, resume in enumerate(applied_resumes):
             resume_id_tag = f"RESUME_ID_{resume.id}"
             resumes_text += f"--- Candidate {resume_id_tag} ---\n"
             if resume.full_name and resume.full_name != "Not found":
                 resumes_text += f"Name: {resume.full_name}\n"
             # Include extracted fields if available and not 'Not found'
             if resume.skills and resume.skills != "Not found":
                 resumes_text += f"Skills: {resume.skills}\n"
             if resume.experience and resume.experience != "Not found":
                 # Limit length slightly to avoid overly long prompts
                 exp_summary = (resume.experience[:1000] + '...') if len(resume.experience) > 1000 else resume.experience
                 resumes_text += f"Experience Summary: {exp_summary}\n"
             # Include content snippet or summary if needed, kept original logic
             if resume.content:
                 # Limit content length
                 content_summary = (resume.content[:1500] + '...') if len(resume.content) > 1500 else resume.content
                 resumes_text += f"Resume Text Snippet:\n{content_summary}\n\n"
             else:
                  resumes_text += "Resume Text: [Not Available]\n\n"
             resume_map[resume_id_tag] = resume

        prompt = (
            f"{vacancy_details}"
            "Analyze ONLY the following candidate resumes who have applied for this specific vacancy:\n\n"
            f"{resumes_text}"
            "Task: Select the SINGLE MOST SUITABLE candidate for this vacancy based ONLY on the provided information. "
            "Briefly justify your choice (2-3 sentences), highlighting key matches with the requirements. "
            "Format your response EXACTLY as follows:\n"
            "Best Candidate: RESUME_ID_XXX\n"
            "Justification: [Your justification here]"
        )

        try:
            print(f"Sending request to Gemini API for vacancy {vacancy_id} with {len(applied_resumes)} applicants...")
            response = gemini_model.generate_content(prompt)
            print(f"Received response from Gemini API.")

            match = re.search(r"Best Candidate:\s*(RESUME_ID_\d+)", response.text, re.IGNORECASE)
            justification = response.text # Default justification is the full response text

            if match:
                best_candidate_tag = match.group(1).upper()
                best_candidate_resume = resume_map.get(best_candidate_tag)

                # Try to extract justification part after the ID line
                try:
                    justification_part = response.text.split(match.group(0), 1)[1].strip()
                    if justification_part.lower().startswith("justification:"):
                        justification = justification_part.split(":", 1)[1].strip()
                    else:
                        justification = justification_part
                except IndexError:
                    justification = "Justification not found after ID line."


                if best_candidate_resume:
                    return jsonify({
                        "vacancy_id": vacancy_id, # Added for context
                        "vacancy_title": vacancy.title, # Added for context
                        "best_candidate": {
                            "id": best_candidate_resume.id, # Changed key to 'id'
                            "filename": best_candidate_resume.filename,
                            "full_name": best_candidate_resume.full_name,
                            "email": best_candidate_resume.email,
                            "phone": best_candidate_resume.phone,
                            "skills": best_candidate_resume.skills,
                            "experience": best_candidate_resume.experience
                        },
                        "gemini_justification": justification,
                    })
                else:
                    print(f"Error: Gemini returned ID {best_candidate_tag}, but no resume with this ID was found in the applicant map for vacancy {vacancy_id}.")
                    return jsonify({"error": f"Data consistency error: Gemini selected applicant {best_candidate_tag}, but they were not found in the current applicant list.", "gemini_response": response.text}), 500
            else:
                print("Error: Could not extract the best candidate ID from the Gemini response.")
                 # Check for potential blocks or refusals
                try:
                    if response.prompt_feedback.block_reason:
                         block_reason = response.prompt_feedback.block_reason.name
                         print(f"Gemini response blocked. Reason: {block_reason}")
                         return jsonify({"error": f"Gemini response blocked. Reason: {block_reason}", "gemini_response": response.text}), 400
                except (AttributeError, IndexError):
                     pass # Continue to generic error
                return jsonify({"error": "Could not determine the best candidate ID from the Gemini response format.", "gemini_response": response.text}), 500

        except Exception as gemini_err:
             print(f"Error calling Gemini API: {gemini_err}")
             return jsonify({"error": f"Error interacting with Gemini API: {str(gemini_err)}"}), 500

    except Exception as e:
        import traceback
        print(f"Error in endpoint /api/best_candidate/{vacancy_id}:\n{traceback.format_exc()}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        # Ensure session is always closed
        if session.is_active:
            session.close()


if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
        print(f"Created upload folder: {UPLOAD_FOLDER}")
    print("Starting Flask app (JSON API only)...")
    # Use host='0.0.0.0' to make it accessible on the network if needed
    app.run(debug=True, host='0.0.0.0', port=5000)