"""
Edit this file with your own details before running the bot.
"""

USER_PROFILE = {
    "name": "Your Name",
    "email": "you@example.com",
    "phone": "+91 9999999999",
    "location": "City, India",
    "linkedin": "https://www.linkedin.com/in/your-profile",
    "github": "https://github.com/your-username",
    "notice_period": "Immediate",           # or "1 month", "2 months", etc.
    "current_salary_lpa": 0.0,
    "expected_salary_lpa": 0.0,
    "min_salary_lpa": 0.0,
    "total_experience_years": 0.0,
    "open_to": ["Remote", "India"],
    "visa_required_for_foreign": True,

    "summary": (
        "Write a 2–3 sentence professional summary here. "
        "This is used by the Ollama model to score jobs and generate cover letters."
    ),

    "skills": [
        # Add your skills here
        "Python", "Machine Learning", "Deep Learning",
    ],

    "experience": [
        {
            "company": "Company Name",
            "role": "Your Role",
            "duration": "Jan 2023 – Present",
            "highlights": [
                "Key achievement or responsibility",
                "Another highlight",
            ],
        },
    ],

    "education": {
        "degree": "B.Tech, Your Branch",
        "institution": "Your College",
        "year": "2019–2023",
    },

    "target_roles": [
        "ML Engineer",
        "AI Engineer",
        # Add more target role titles here
    ],

    # These are used to auto-fill common form fields on job applications
    "form_answers": {
        "years_of_experience": "2",
        "notice_period": "Immediate",
        "current_ctc": "0 LPA",
        "expected_ctc": "0 LPA",
        "work_authorization_india": "Yes",
        "sponsorship_required": "No",
        "relocate": "Yes",
        "remote_ok": "Yes",
        "highest_education": "B.Tech",
        "degree": "Bachelor of Technology",
        "field_of_study": "Your Field",
        "gpa": "0.0",
        "cover_letter_default": (
            "Write your default cover letter here. "
            "This is used as a fallback if the LLM-generated one fails."
        ),
    },
}
