"""
prompts.py
----------
All GPT prompt templates for the Recruitment AI system.
Keep them here — not scattered through the codebase — so you can
find, test, and improve them without touching business logic.
"""


def build_jd_parse_prompt(jd_text: str, filename: str = "") -> str:
    source_hint = f"Source filename: {filename}\n\n" if filename else ""
    return f"""You are reading an internal job description file used by a recruitment agency.
These files are often informal and written recruiter-to-recruiter, not as polished external postings.

Important rules:
- The file may contain ONE role or MULTIPLE distinct roles bundled together.
  Detect each role separately and return all of them.
- The file may contain recruiter notes or admin instructions that are NOT
  part of any role (e.g. 'please check existing pool', 'kindly review recently submitted profiles').
  Ignore these completely when extracting requirements.
- For required_skills: extract ONLY clean skill keywords and technology names.
  DO NOT copy requirement phrases. Extract the core skill from each requirement.
  Examples of correct extraction:
    "hands-on experience with Python" → "Python"
    "expertise in SQL" → "SQL"
    "strong experience working with large datasets" → "data analysis"
    "experience with Airflow and DBT pipelines" → "Airflow", "DBT"
    "strong understanding of cloud platforms" → "cloud platforms"
    "3+ years experience with React" → "React"
  Each item in required_skills must be a short skill name or technology (1-4 words max),
  never a full sentence or requirement phrase.
- For nice_to_have_skills: same rule — clean keywords only, not phrases.
- If years of experience is not explicitly stated, infer it from seniority language
  (e.g. 'senior' = 5+, 'junior' = 0-2, 'mid-level' = 2-5) or leave as null.
- Domain means the industry or functional area (e.g. 'banking', 'healthcare', 'general IT').

{source_hint}Return ONLY valid JSON, no markdown, no code fences, no commentary.
Shape:
{{
  "roles": [
    {{
      "title": "exact role title as written",
      "required_skills": ["Python", "SQL", "Airflow"],
      "nice_to_have_skills": ["Tableau", "PowerBI"],
      "min_years_experience": <number or null>,
      "domain": "banking | healthcare | general IT | fintech | etc",
      "summary": "one sentence: who is the ideal candidate for this role"
    }}
  ]
}}

Job description text:
{jd_text}"""


def build_cv_parse_prompt(cv_text: str) -> str:
    return f"""You are reading a candidate CV submitted to a recruitment agency.
CVs vary widely in format — some have dedicated skills sections, others bury
skills inside job descriptions. Extract everything relevant.

Rules:
- For years_experience: calculate from total working years in the CV,
  not just what the candidate claims. If unclear, estimate conservatively.
- For skills: include both explicitly listed skills AND tools/tech mentioned
  within individual job descriptions. Extract ONLY actual skills and technologies
  (e.g. Python, SQL, AWS, Agile) — do NOT include experience descriptions or
  sentences as skills.
- For domain_experience: list actual industry sectors the candidate has
  worked in. E.g. ['banking', 'insurance', 'e-commerce'].
- For work_rights: extract exactly as written (e.g. 'Australian Citizen',
  'PR', 'Temporary Graduate Visa 485'). If not mentioned, use null.
- For notice_period: if stated, extract it (e.g. '2 weeks', '1 month', 'immediate').
  If not mentioned, use null.
- For work_experience: extract each role as a separate object. If not present, return [].
- For projects: extract concrete projects, technologies, and outcomes. If not present, return [].
- For certifications: extract only certifications explicitly stated. If not present, return [].
- For education: extract each qualification. If not present, return [].
- For key_achievements: extract 3-5 standout bullet points from the CV. If none, return [].

Return ONLY valid JSON, no markdown, no code fences, no commentary.
Shape:
{{
  "name": "full name if present, else null",
  "email": "email if present, else null",
  "phone": "phone if present, else null",
  "skills": ["actual skill or technology only", "not sentences"],
  "years_experience": <number or null>,
  "domain_experience": ["banking", "insurance"],
  "work_rights": "Australian Citizen | PR | null",
  "notice_period": "2 weeks | immediate | null",
  "summary": "one sentence: what kind of candidate this is and what they are best suited for",
  "work_experience": [
    {{
      "title": "job title",
      "company": "company name",
      "start_year": 2021,
      "end_year": null,
      "is_current": true,
      "highlights": ["key achievement or responsibility"]
    }}
  ],
  "projects": [
    {{
      "name": "project name",
      "description": "what was built",
      "technologies": ["explicitly stated technology"],
      "highlights": ["concrete project outcome or responsibility"]
    }}
  ],
  "certifications": ["certification exactly as stated"],
  "education": [
    {{
      "degree": "B.Sc. Computer Science",
      "institution": "University name",
      "year": 2017
    }}
  ],
  "key_achievements": [
    "Led team of 5 developers on enterprise platform",
    "Reduced load time by 40%"
  ]
}}

CV text:
{cv_text}"""


def build_embedding_text_from_job(parsed_job: dict) -> str:
    """
    Constructs the string that gets sent to the embedding model for a job.
    NOT a GPT prompt — this is the text that gets vectorised.
    """
    skills = ", ".join(parsed_job.get("required_skills", []))
    nice = ", ".join(parsed_job.get("nice_to_have_skills", []))
    domain = parsed_job.get("domain", "general")
    summary = parsed_job.get("summary", "")
    years = parsed_job.get("min_years_experience")
    exp_str = f"{years}+ years experience required." if years else ""

    return f"{summary} Domain: {domain}. Required skills: {skills}. {exp_str} Nice to have: {nice}."


def build_embedding_text_from_candidate(parsed_candidate: dict) -> str:
    """
    Constructs the string that gets sent to the embedding model for a candidate.
    Mirrors the job embedding structure so the vector spaces align properly.
    """
    skills = ", ".join(parsed_candidate.get("skills", []))
    domain = ", ".join(parsed_candidate.get("domain_experience", []))
    summary = parsed_candidate.get("summary", "")
    years = parsed_candidate.get("years_experience")
    exp_str = f"{years} years experience." if years else ""

    return f"{summary} Domain experience: {domain}. Skills: {skills}. {exp_str}"


def build_uplift_prompt(cv_raw: str, parsed_candidate: dict, parsed_job: dict) -> str:
    """
    Prompt for the Uplifted pipeline stage — rewrites a candidate profile
    tailored to a specific job. Does NOT fabricate skills.
    """
    required_skills = ", ".join(parsed_job.get("required_skills", []))
    job_summary = parsed_job.get("summary", "")
    candidate_summary = parsed_candidate.get("summary", "")

    return f"""You are a professional recruitment consultant rewriting a candidate profile
to better align with a specific job opportunity.

IMPORTANT RULES:
- Do NOT invent, fabricate, or exaggerate any skills or experience.
- Only reframe and emphasise experience that is genuinely present in the original CV.
- Write in clear, professional third-person prose (e.g. 'Asha brings 6 years of...').
- Highlight how the candidate's existing experience maps to the role's requirements.
- Keep it concise — no more than 300 words.
- Do not use hollow phrases like 'passionate', 'driven', 'rockstar', or 'ninja'.

Target role: {job_summary}
Required skills for this role: {required_skills}

Candidate overview: {candidate_summary}

Original CV:
{cv_raw}

Write the uplifted profile now:"""
