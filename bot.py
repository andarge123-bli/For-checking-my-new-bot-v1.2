"""
MTU University File-Sharing Telegram Bot — v3.0

New in v3.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEW FEATURES
  • PREDEFINED_COURSES completely replaced with accurate data from the official
    MTU course PDF. Every course list is now semester-by-semester per
    department, reflecting the actual university curriculum.

  • Year 1 courses are now stream-based commons:
      – Engineering & Technology stream common (Year 1)
      – Natural Science stream common (Year 1)
      – Health Sciences stream common (Year 1)
      – Agriculture stream common (Year 1)
      – Social Sciences stream common (Year 1)
    These are stored under the Freshman faculty for each stream.

  • New onboarding year-selection step:
      After selecting Faculty and Department during onboarding, the user is
      now asked to select their current year (e.g. Year 1, Year 2 … Year 5).
      Only the correct number of years for the chosen department is shown.
      The year is saved in the user profile.

  • Year-aware notifications:
      _notify_department_users() now also compares the uploaded file's year
      against the user's saved year. A user only receives a notification if
      both department AND year match.

  • New / corrected departments in FACULTIES:
      – "💧 Hydraulic and Water Resource Engineering" (Engineering)
      – "🌿 Environmental Science" (Agriculture)
      – "🐄 Veterinary Science" (Agriculture)
      – "📝 Amharic & Ethiopian Language" (Social Sciences)
      – "🤲 Social Work" replaces the placeholder
      (All departments that were already present but lacked PDF data remain
      usable; users can still create custom courses for them.)

All v2.2 bug fixes are preserved.
"""

import logging
import os
import re
import sys
import time
import json
import signal
import threading
import io
import concurrent.futures
from flask import Flask

import telebot
from telebot import types

try:
    from google import genai
    from google.genai import types as genai_types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

BOT_TOKEN  = os.environ.get("BOT_TOKEN", "xxxxxxxxxx")
OWNER_ID   = 5392468999
GROUP_LINK = os.environ.get("GROUP_LINK", "https://t.me/mtu_files_group")

GOOGLE_API_KEYS = [
    os.environ.get("GOOGLE_API_KEY_1", os.environ.get("GOOGLE_API_KEY", "")),
    os.environ.get("GOOGLE_API_KEY_2", ""),
    os.environ.get("GOOGLE_API_KEY_3", ""),
    os.environ.get("GOOGLE_API_KEY_4", ""),
    os.environ.get("GOOGLE_API_KEY_5", ""),
]
GOOGLE_API_KEYS = [k for k in GOOGLE_API_KEYS if k]

print(f"[STARTUP] GEMINI_AVAILABLE={GEMINI_AVAILABLE}")
print(f"[STARTUP] GOOGLE_API_KEYS count={len(GOOGLE_API_KEYS)}")
if not GEMINI_AVAILABLE:
    print("[STARTUP] WARNING: google-genai not installed. Run: pip install google-genai")
if not GOOGLE_API_KEYS:
    print("[STARTUP] WARNING: No Google API keys found. Set GOOGLE_API_KEY_1…5 env vars.")

# ── Action name constants ─────────────────────────────────────────────────────

ACTION_AI_CHAT             = "ai_chat"
ACTION_CONTACT             = "contact"
ACTION_SEARCH              = "search"
ACTION_ADMIN_DELETE        = "admin_delete"
ACTION_ADMIN_DELETE_COURSE = "admin_delete_course"
ACTION_ADMIN_BROADCAST     = "admin_broadcast"
ACTION_ADMIN_DM_TARGET     = "admin_dm_target"
ACTION_ADMIN_DM_MESSAGE    = "admin_dm_message"
ACTION_ADMIN_REPLY         = "admin_reply"
ACTION_CREATING_COURSE     = "creating_course"
ACTION_CREATING_UPLOAD_CRS = "creating_upload_course"
ACTION_AWAITING_FILE       = "awaiting_file"
ACTION_ONBOARDING_FAC      = "onboarding_faculty"
ACTION_ONBOARDING_DEPT     = "onboarding_dept"
ACTION_ONBOARDING_YEAR     = "onboarding_year"   # NEW in v3.0

# ── API-key rotation ──────────────────────────────────────────────────────────

_api_key_index = 0
_api_key_lock  = threading.Lock()


def get_next_api_key() -> str | None:
    global _api_key_index
    with _api_key_lock:
        if not GOOGLE_API_KEYS:
            return None
        key = GOOGLE_API_KEYS[_api_key_index % len(GOOGLE_API_KEYS)]
        _api_key_index = (_api_key_index + 1) % len(GOOGLE_API_KEYS)
        return key


# ── Bot instance ──────────────────────────────────────────────────────────────

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None, num_threads=8)

# ── Channel-DB config ─────────────────────────────────────────────────────────

DB_CHANNEL_ID = int(os.environ.get("DB_CHANNEL_ID", "0"))
DB_MSG_IDS: dict = {}

# ── AI chat histories (in-memory, per user) ───────────────────────────────────

ai_chat_histories: dict = {}
ai_histories_lock = threading.Lock()

# ── Owner reply routing ───────────────────────────────────────────────────────

pending_reply_targets: dict = {}
pending_reply_lock = threading.Lock()

# ── Faculty / Department data ─────────────────────────────────────────────────

FACULTIES: dict[str, list[str]] = {
    "🔧 Engineering and Technology": [
        "💻 Software Engineering",
        "⚡ Electrical & Computer Engineering",
        "⚙️ Mechanical Engineering",
        "🏗️ Civil Engineering",
        "🏗️ Construction Technology & Management",
        "📐 Surveying Engineering",
        "🖥️ Computer Science",
        "🌐 Information Technology",
        "🌊 Hydraulic and Water Resource Engineering",
        "🗄️ Information System",
        "🏭 Industrial Engineering",
        "💧 Water Resources & Irrigation Engineering",
        "🧱 Architecture",
        "⚗️ Chemical Engineering",
        "🌾 Agricultural Engineering",
    ],
    "🔬 Natural Sciences": [
        "⚛️ Physics",
        "🧪 Chemistry",
        "🧬 Biology",
        "📐 Mathematics",
        "📊 Statistics",
        "🌍 Geology",
        "🌿 Environmental Science",
        "🏃 Sport Science",
    ],
    "🏥 Health Sciences": [
        "💉 Nursing",
        "🩺 Medicine",
        "💊 Pharmacy",
        "🌡️ Public Health",
        "👶 Midwifery",
        "🔬 Medical Laboratory Science",
        "😴 Anesthesia",
        "🌱 Environmental Health",
        "🧠 Psychiatry",
    ],
    "🌾 Agriculture": [
        "🌱 Agribusiness & Value Chain Management",
        "📈 Agricultural Economics",
        "🐄 Animal Science",
        "🌳 Forestry",
        "🌿 Horticulture",
        "🏞️ Natural Resource Management",
        "🌾 Plant Science",
        "💧 Soil & Water Resource Management",
        "🌿 Environmental Science",
        "🐄 Veterinary Science",
    ],
    "🏛️ Social Sciences & Humanities": [
        "💼 Accounting & Finance",
        "🤝 Cooperative Business Management",
        "📉 Economics",
        "📋 Management",
        "📣 Marketing Management",
        "📝 Amharic & Ethiopian Language",
        "⚖️ Civics & Ethical Studies",
        "📖 English Language & Literature",
        "🗺️ Geography & Environmental Studies",
        "🏛️ Governance & Development Studies",
        "📜 History & Heritage Management",
        "📻 Journalism & Communication",
        "🎓 Educational Planning & Management",
        "🧠 Psychology",
        "🤲 Social Work",
        "👥 Sociology",
        "🤝 Cooperative Accounting & Auditing",
    ],
    "⚖️ Law": ["⚖️ Law"],
    "🎓 Freshman": [],
    "🎯 Remedial": [],
}

SPECIAL_FACULTIES     = {"Freshman", "Remedial"}
NO_SEMESTER_FACULTIES = {"Remedial"}

# ── Department year count (how many years each dept has) ─────────────────────
# Used to build the correct year keyboard during onboarding and browsing.
# Departments not listed here default to 4 years.

DEPT_YEAR_COUNT: dict[str, int] = {
    # Engineering 5-year programmes
    "Civil Engineering": 5,
    "Construction Technology & Management": 5,
    "Electrical & Computer Engineering": 5,
    "Hydraulic and Water Resource Engineering": 5,
    "Mechanical Engineering": 5,
    "Surveying Engineering": 5,
    # Health 5-year programme
    "Pharmacy": 5,
    # Law 5-year programme
    "Law": 5,
    # All others default to 4 — not listed here
}


def get_dept_year_count(dept: str) -> int:
    """Return the number of years for a department (stripped of emoji)."""
    dept_clean = strip_emoji(dept).strip() if dept else ""
    return DEPT_YEAR_COUNT.get(dept_clean, 4)


# ── Predefined MTU Course Directory (from official PDF) ──────────────────────
# Key format: (faculty_clean, dept_clean, year_label, semester_label)
# faculty_clean and dept_clean have emojis stripped.
# Year 1 for each stream is stored with the stream's common key.

PREDEFINED_COURSES: dict[tuple, list[str]] = {

    # ══════════════════════════════════════════════════════════════════════════
    # ENGINEERING & TECHNOLOGY — Year 1 Common (Freshman for Eng stream)
    # ══════════════════════════════════════════════════════════════════════════
    ("Freshman", "", "", "Sem1"): [
        "Communicative English Skills I", "General Physics", "General Psychology",
        "Mathematics for Natural Science", "Critical Thinking", "Physical fitness",
        "Geography of Ethiopia & the Horn",
    ],
    ("Freshman", "", "", "Sem2"): [
        "Communicative English Skills II", "Social Anthropology",
        "Basic Engineering Course - Applied Maths I",
        "History of Ethiopia & the Horn", "Introduction to emerging Technologies",
        "Moral and Civic Education",
        "Basic Engineering Course - Computer Programming",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # 1. CIVIL ENGINEERING
    # ══════════════════════════════════════════════════════════════════════════
    ("Engineering and Technology", "Civil Engineering", "Year2", "Sem1"): [
        "Engineering Mechanics I", "Engineering Drawing", "Applied Mathematics II",
        "Probability and Statistics", "Introduction to International Relations and Global Issues",
        "Introduction to Economics", "Inclusiveness",
    ],
    ("Engineering and Technology", "Civil Engineering", "Year2", "Sem2"): [
        "Hydraulics", "Strength of Materials", "Transport Planning and Modelling",
        "Civil Engineering Workshop Practice", "Engineering Mechanics II",
        "Engineering Surveying I", "Engineering Geology",
    ],
    ("Engineering and Technology", "Civil Engineering", "Year3", "Sem1"): [
        "Theory of Structures I", "Engineering Surveying II", "Numerical Methods",
        "Open Channel Hydraulics", "Fundamentals of Geotechnical Engineering I",
        "Traffic & Road Safety Engineering", "Construction Materials",
    ],
    ("Engineering and Technology", "Civil Engineering", "Year3", "Sem2"): [
        "Engineering Hydrology", "Reinforced Concrete Structures I",
        "Geometric Design of Highways and Streets",
        "Fundamentals of Geotechnical Engineering II", "Hydraulic Structure I",
        "Integrated Surveying Field Practice", "Fundamentals of Architecture",
    ],
    ("Engineering and Technology", "Civil Engineering", "Year4", "Sem1"): [
        "Water Supply and Treatment", "Hydraulic Structures II",
        "Contract specification and quantity survey",
        "Pavement Materials Analysis and Design", "Geotechnical Engineering Design I",
        "Technical Report Writing & Research Methods",
        "Reinforced Concrete Structures II", "Building Construction",
    ],
    ("Engineering and Technology", "Civil Engineering", "Year4", "Sem2"): [
        "Internship Practice",
    ],
    ("Engineering and Technology", "Civil Engineering", "Year5", "Sem1"): [
        "Geotechnical Engineering Design-II", "Construction Equipment",
        "Irrigation Engineering", "Waste Water treatment", "Environmental Engineering",
        "Integrated Civil Engineering Design", "Elective 1",
    ],
    ("Engineering and Technology", "Civil Engineering", "Year5", "Sem2"): [
        "Steel & Timber Structures", "Construction Project Management",
        "BSC Thesis", "Elective 2", "Engineering Economics", "Elective 3",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # 2. CONSTRUCTION TECHNOLOGY & MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════
    ("Engineering and Technology", "Construction Technology & Management", "Year2", "Sem1"): [
        "Principles of Accounting", "Engineering Mechanics", "Engineering Drawing",
        "Workshop Practice", "Construction Materials I", "Introduction to Economics",
        "Principles of Construction Management",
    ],
    ("Engineering and Technology", "Construction Technology & Management", "Year2", "Sem2"): [
        "Building Construction I", "Construction Materials II",
        "Construction Drafting and Working Drawing", "Probability and Statistics",
        "Strength of Materials", "Hydraulics",
    ],
    ("Engineering and Technology", "Construction Technology & Management", "Year3", "Sem1"): [
        "Building Construction II", "Theory of Structures", "Water Supply and Treatment",
        "Soil Mechanics", "Surveying", "Computer Aided Drafting",
    ],
    ("Engineering and Technology", "Construction Technology & Management", "Year3", "Sem2"): [
        "Architectural Planning and Design", "Design of Reinforced Concrete Structures",
        "Sewage Disposal & Treatment", "Foundation Engineering", "Highway Engineering I",
    ],
    ("Engineering and Technology", "Construction Technology & Management", "Year4", "Sem1"): [
        "Construction Equipment and Plant Management", "Highway Engineering II",
        "Health and Safety Management in Construction",
        "Construction Planning & Scheduling", "Cost Engineering",
        "Design and Construction of Water Works", "Construction Law",
    ],
    ("Engineering and Technology", "Construction Technology & Management", "Year4", "Sem2"): [
        "Technical Report Writing & Research Methods",
        "Construction Site Supervision", "Internship",
    ],
    ("Engineering and Technology", "Construction Technology & Management", "Year5", "Sem1"): [
        "Financial Management in Construction", "Bridge and Tunnel Construction",
        "Construction Procurement and Contract Management",
        "Development and construction Economics",
        "Design of Steel and Timber Structures", "Holistic Project",
    ],
    ("Engineering and Technology", "Construction Technology & Management", "Year5", "Sem2"): [
        "Construction Performance & Resource Optimization",
        "Modern Construction Technology and BIM", "BSc. Research",
        "Global Trends", "Inclusiveness", "Elective",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # 3. ELECTRICAL & COMPUTER ENGINEERING
    # ══════════════════════════════════════════════════════════════════════════
    ("Engineering and Technology", "Electrical & Computer Engineering", "Year2", "Sem1"): [
        "Engineering Drawing", "Engineering Mechanics I (Statics)",
        "Applied Engineering Mathematics II", "Probability and Random Process",
        "International relations and Global issues", "Introduction to Economics",
        "Inclusiveness Education",
    ],
    ("Engineering and Technology", "Electrical & Computer Engineering", "Year2", "Sem2"): [
        "Fundamentals of Electrical Engineering", "Electrical Engineering Lab I",
        "Applied Mathematics III", "Engineering Mechanics II (Dynamics)",
        "Electrical Workshop Practice I", "Applied Modern Physics",
        "Engineering Thermodynamics",
    ],
    ("Engineering and Technology", "Electrical & Computer Engineering", "Year3", "Sem1"): [
        "Object Oriented Programming", "Computational Methods", "Applied Electronics I",
        "Electrical Engineering Lab II", "Electromagnetic Fields",
        "Signals and System Analysis", "Introduction to Electrical Machines",
    ],
    ("Engineering and Technology", "Electrical & Computer Engineering", "Year3", "Sem2"): [
        "Network Analysis and Synthesis", "Digital Logic Design",
        "Electrical Materials and Technology", "Machines Lab",
        "Electrical Workshop Practice II", "Applied Electronics II",
        "Electrical Engineering Lab III", "Computer architecture and Organization",
    ],
    ("Engineering and Technology", "Electrical & Computer Engineering", "Year4", "Sem1"): [
        "Introduction to Communication Systems", "Digital Signal Processing",
        "Introduction to Control Engineering", "Introduction to Power Systems",
        "Electrical Engineering Laboratory V", "Introduction to Instrumentation",
        "Microcomputers and Interfacing",
    ],
    ("Engineering and Technology", "Electrical & Computer Engineering", "Year4", "Sem2"): [
        "Data Structures", "Software Engineering", "Computer and Network Security",
        "Data Communication & Computer Networks", "Database Systems",
        "Research Methods and Presentation", "Semester Project",
    ],
    ("Engineering and Technology", "Electrical & Computer Engineering", "Year5", "Sem1"): [
        "Industry Internship", "Introduction to Compilers", "Introduction to Robotics",
    ],
    ("Engineering and Technology", "Electrical & Computer Engineering", "Year5", "Sem2"): [
        "Operating systems", "Algorithms Analysis and Design", "Embedded Systems",
        "VLSI Design", "B.Sc. Project",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # 4. HYDRAULIC AND WATER RESOURCE ENGINEERING
    # ══════════════════════════════════════════════════════════════════════════
    ("Engineering and Technology", "Hydraulic and Water Resource Engineering", "Year2", "Sem1"): [
        "Engineering Drawing", "Engineering Mechanics (Static)",
        "Basic Electricity and Electrical Machine", "General Workshop Practice",
        "Applied Mathematics-II", "Surveying-I", "Construction Materials and Equipment",
    ],
    ("Engineering and Technology", "Hydraulic and Water Resource Engineering", "Year2", "Sem2"): [
        "Numerical Methods for Engineer", "Probability and Statistics",
        "Surveying II", "Building construction", "Strength of Materials",
        "Fluid Mechanics", "Introduction to Hydrology",
    ],
    ("Engineering and Technology", "Hydraulic and Water Resource Engineering", "Year3", "Sem1"): [
        "Engineering Geology & Rock Mechanics", "Soil Mechanics I", "Hydraulics",
        "Reinforced Concrete Design-I", "Engineering Hydrology",
        "Open Channel Hydraulics", "Hydrological Measurements and Analysis",
    ],
    ("Engineering and Technology", "Hydraulic and Water Resource Engineering", "Year3", "Sem2"): [
        "Soil Mechanics II", "Reinforced Concrete Design-II",
        "Ground Water Engineering", "Hydraulic Structures I",
        "Hydropower Engineering-I", "Water Supply & Treatment", "Irrigation Engineering",
    ],
    ("Engineering and Technology", "Hydraulic and Water Resource Engineering", "Year4", "Sem1"): [
        "Foundation Engineering", "Contract Specification and Quantity Surveying",
        "Hydraulic Structures II", "Hydropower Engineering-II",
        "Waste Water & Solid Waste Management",
        "Software in Hydraulic Engineering", "Research Methods and Report Writing",
    ],
    ("Engineering and Technology", "Hydraulic and Water Resource Engineering", "Year4", "Sem2"): [
        "Holistic Examination", "Internship",
    ],
    ("Engineering and Technology", "Hydraulic and Water Resource Engineering", "Year5", "Sem1"): [
        "Engineering Economics", "Hydraulic Machines",
        "Water Resources Planning & Management",
        "River Engineering & sediment transport", "Environmental Impact Assessment",
        "Road Engineering", "GIS and Remote Sensing",
    ],
    ("Engineering and Technology", "Hydraulic and Water Resource Engineering", "Year5", "Sem2"): [
        "Construction Planning and Management", "Watershed Management",
        "Water law and hydro politics", "Bridge and Culvert hydraulics",
        "Entrepreneurship for Engineers", "Educational Field Practice",
        "Bachelor Thesis",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # 5. MECHANICAL ENGINEERING
    # ══════════════════════════════════════════════════════════════════════════
    ("Engineering and Technology", "Mechanical Engineering", "Year2", "Sem1"): [
        "Engineering Drawing", "Engineering Mechanics - I (Statics)",
        "Applied Eng. Mathematics II", "Probability and Statistics for Engineers",
        "Inclusiveness", "Introduction to Economics", "Global Trends",
    ],
    ("Engineering and Technology", "Mechanical Engineering", "Year2", "Sem2"): [
        "Engineering Mechanics II Dynamics", "Applied Mathematics III",
        "Strength of Materials I", "Engineering Thermodynamics I",
        "Engineering Materials I", "Basic Electricity & Electronics",
        "Workshop Practice - I",
    ],
    ("Engineering and Technology", "Mechanical Engineering", "Year3", "Sem1"): [
        "Engineering Materials II", "Engineering Thermodynamics II",
        "Electrical Machines and Drives", "Strength of Materials II",
        "Fluid Mechanics", "Machine Drawing I", "Workshop Practice-II",
    ],
    ("Engineering and Technology", "Mechanical Engineering", "Year3", "Sem2"): [
        "Mechanisms of Machinery", "Heat transfer", "Machine Elements I",
        "Manufacturing Engineering", "Numerical Methods",
        "Machine Drawing II with CAD", "Introduction to Mechatronics",
    ],
    ("Engineering and Technology", "Mechanical Engineering", "Year4", "Sem1"): [
        "Machine Elements II", "Instrumentation and Measurement",
        "Machine Design Project I", "Manufacturing Engineering II",
        "Turbo machinery", "Technical writing & research Methodology",
        "Mechanical Vibration",
    ],
    ("Engineering and Technology", "Mechanical Engineering", "Year4", "Sem2"): [
        "Metrology Lab Exercise", "Internship",
    ],
    ("Engineering and Technology", "Mechanical Engineering", "Year5", "Sem1"): [
        "Pneumatics and Hydraulics", "IC Engines and Reciprocating Machines",
        "Introduction to Finite Element Methods", "Machine Design Project II",
        "Maintenance of Machinery", "Refrigeration and air conditioning",
        "Design of Renewable Energy Systems",
    ],
    ("Engineering and Technology", "Mechanical Engineering", "Year5", "Sem2"): [
        "Power Plant Engineering", "Regulation and Control",
        "Industrial Management & Engineering Economy",
        "Thermo-Fluid System Design", "B.Sc. Thesis",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # 6. SURVEYING ENGINEERING
    # ══════════════════════════════════════════════════════════════════════════
    ("Engineering and Technology", "Surveying Engineering", "Year2", "Sem1"): [
        "Applied Mathematics-II", "Engineering Mechanics-I (Statics)",
        "Fundamentals of Surveying", "Global Trends", "Inclusiveness",
        "Architectural Working Drawing", "Probability and Statistics",
    ],
    ("Engineering and Technology", "Surveying Engineering", "Year2", "Sem2"): [
        "Applied Mathematics III", "Topographic Surveying", "Route Surveying",
        "Geometric Design of Highways and Streets", "Photogrammetry-I",
        "Construction Materials", "Computer Aided Drafting/Design (CAD)",
    ],
    ("Engineering and Technology", "Surveying Engineering", "Year3", "Sem1"): [
        "GIS-I", "Pavement Materials Analysis and Design",
        "Construction Surveying", "Photogrammetry-II", "Cartography",
        "Building Construction",
    ],
    ("Engineering and Technology", "Surveying Engineering", "Year3", "Sem2"): [
        "GIS-II", "Introduction to Geodesy", "Spatial Database Management System",
        "Transportation Planning and Modeling",
        "Global Navigation Satellite System (GNSS)", "Remote Sensing",
    ],
    ("Engineering and Technology", "Surveying Engineering", "Year4", "Sem1"): [
        "Applications of Surveying Software's", "Advanced Geodesy",
        "Theory of Error and Adjustment Computation",
        "Contract Specification and Quantity Surveying",
        "Research Methodology for engineers", "Cadastral Surveying",
    ],
    ("Engineering and Technology", "Surveying Engineering", "Year4", "Sem2"): [
        "Internship",
    ],
    ("Engineering and Technology", "Surveying Engineering", "Year5", "Sem1"): [
        "Railway Engineering", "Engineering Geology", "Land law",
        "Digital Image Analysis", "Surveying Project planning and Management",
        "Urban Land Use Planning",
    ],
    ("Engineering and Technology", "Surveying Engineering", "Year5", "Sem2"): [
        "Land Administration", "Irrigation Engineering",
        "Introduction to Economics", "Senior Project",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # NATURAL SCIENCE — Year 1 Common
    # (Stored under Natural Sciences faculty, empty dept, Year1)
    # ══════════════════════════════════════════════════════════════════════════
    ("Natural Sciences", "", "Year1", "Sem1"): [
        "Communicative English Skills I", "General Physics", "General Psychology",
        "Mathematics for Natural Science", "Critical Thinking", "Physical fitness",
        "Geography of Ethiopia & the Horn",
    ],
    ("Natural Sciences", "", "Year1", "Sem2"): [
        "Communicative English Skills II", "Social Anthropology", "General Biology",
        "History of Ethiopia & the Horn", "Introduction to emerging Technologies",
        "Moral and Civic Education", "General Chemistry",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # 1. COMPUTER SCIENCE
    # ══════════════════════════════════════════════════════════════════════════
    ("Engineering and Technology", "Computer Science", "Year2", "Sem1"): [
        "Digital Logic Design", "Fundamentals Of Programming II",
        "Linear Algebra", "Fundamentals of Database System",
        "Economics", "Probability and Statistics", "Inclusiveness",
    ],
    ("Engineering and Technology", "Computer Science", "Year2", "Sem2"): [
        "Data Communication and Computer Networking",
        "Advanced Database System", "Object Oriented Programming",
        "Global Trends", "Discrete Mathematics and Combinatory",
        "Data Structure and Algorithm", "Computer Organizations and Architecture",
    ],
    ("Engineering and Technology", "Computer Science", "Year3", "Sem1"): [
        "Operating System", "Web Programming", "Java Programming",
        "Numerical Analysis", "Automata and Complexity Theory",
        "Microprocessor and Assembly Language Programming",
    ],
    ("Engineering and Technology", "Computer Science", "Year3", "Sem2"): [
        "Wireless Communications and Mobile Computing",
        "Design and Analysis of Algorithms", "Real Time and Embedded System",
        "Computer Graphics", "Software Engineering",
        "Introduction to Artificial Intelligence",
    ],
    ("Engineering and Technology", "Computer Science", "Year4", "Sem1"): [
        "Computer Security", "Computer Vision and Image Processing",
        "Research Methods in Computer Science", "Elective I",
        "Compiler Design", "Final Year Project I", "Industrial Practice",
    ],
    ("Engineering and Technology", "Computer Science", "Year4", "Sem2"): [
        "Introduction to Distributed System", "Network and System Administration",
        "Selected Topics in Computer Science", "Elective II", "Final Year Project II",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # 2. INFORMATION SYSTEMS
    # ══════════════════════════════════════════════════════════════════════════
    ("Engineering and Technology", "Information System", "Year2", "Sem1"): [
        "Global Trends and International Relations", "Economics",
        "Introduction to Information Systems and Society",
        "Basic Computer Programming II", "System Analysis and Design",
        "Discrete Mathematics and Combinatory", "Introduction to Management",
    ],
    ("Engineering and Technology", "Information System", "Year2", "Sem2"): [
        "Inclusiveness", "Object Oriented Programming",
        "Fundamentals of Accounting", "Fundamentals of Database Systems",
        "Computer Organization and Architecture", "Data Structure and Algorithms",
    ],
    ("Engineering and Technology", "Information System", "Year3", "Sem1"): [
        "Data Communication and computer Networks", "Introduction to Statistics",
        "Operating Systems", "Research Methods in Information Systems",
        "Event Driven Programming", "Advanced Database Systems",
        "Human Computer Interaction",
    ],
    ("Engineering and Technology", "Information System", "Year3", "Sem2"): [
        "Introduction to Information Storage & Retrieval",
        "Mobile Application Development", "Internet Programming",
        "Fundamentals of Artificial Intelligence",
        "Systems and Network Administration", "Seminar in Information System",
    ],
    ("Engineering and Technology", "Information System", "Year4", "Sem1"): [
        "Elective I", "Knowledge Management", "Introduction to Machine Learning",
        "Information System Security", "Information Systems Project Management",
        "Final Year Project I", "Industrial practice",
    ],
    ("Engineering and Technology", "Information System", "Year4", "Sem2"): [
        "Management of information system and services", "Elective II",
        "Final Year Project II", "Enterprise Systems", "Organizational Behavior",
        "Multimedia Information Systems",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # 3. INFORMATION TECHNOLOGY
    # ══════════════════════════════════════════════════════════════════════════
    ("Engineering and Technology", "Information Technology", "Year2", "Sem1"): [
        "Global Trends and International Relations", "Inclusiveness", "Economics",
        "Fundamentals of Programming II", "Fundamentals of Database Systems",
        "Introduction to Statistics", "Fundamentals of Electricity and Electronics Device",
    ],
    ("Engineering and Technology", "Information Technology", "Year2", "Sem2"): [
        "Advanced Database Systems", "Computer Organization and Architecture",
        "Data Communication and Computer Networks",
        "Data structure and Algorithms", "Discrete Mathematics", "Internet Programming I",
    ],
    ("Engineering and Technology", "Information Technology", "Year3", "Sem1"): [
        "System Analysis and Design", "Multimedia Systems",
        "Object Oriented Programming in Java", "Internet Programming II",
        "Operating Systems", "Computer Maintenance and Technical Support",
    ],
    ("Engineering and Technology", "Information Technology", "Year3", "Sem2"): [
        "Introduction to Distributed Systems", "Information Technology Project Management",
        "Event-Driven Programming", "Information Storage and Retrieval",
        "Advanced Programming", "Mobile Application Development",
    ],
    ("Engineering and Technology", "Information Technology", "Year4", "Sem1"): [
        "Artificial Intelligence", "Industrial Practice",
        "Information Assurance and Security", "Final year Project I",
        "GIS and Remote Sensing", "Basic Research Method in IT",
        "Network Device and Configuration", "Seminar on Current Trends in IT",
    ],
    ("Engineering and Technology", "Information Technology", "Year4", "Sem2"): [
        "Final year Project II", "System and Network Administration",
        "Social and Professional Ethics in IT", "Network Design",
        "Elective", "Wireless Networking and Telecom Technologies",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # NATURAL SCIENCES — BIOLOGY
    # ══════════════════════════════════════════════════════════════════════════
    ("Natural Sciences", "Biology", "Year2", "Sem1"): [
        "Global Trends", "Biological laboratory and field techniques",
        "Cell Biology", "Phycology", "General Microbiology",
        "Inorganic chemistry", "Fundamentals of Biostatistics",
    ],
    ("Natural Sciences", "Biology", "Year2", "Sem2"): [
        "Bryophyte and Pteridophytes", "Inclusiveness", "Soil Science",
        "Mycology", "Invertebrate Zoology", "General Entomology",
        "Fundamentals of Analytical Chemistry", "Practical Analytical Chemistry",
    ],
    ("Natural Sciences", "Biology", "Year3", "Sem1"): [
        "Vertebrate Zoology", "Seed plants", "Applied Entomology",
        "Principles of Parasitology", "Principles of Genetics",
        "Fundamentals of Organic Chemistry", "Practical Organic chemistry",
    ],
    ("Natural Sciences", "Biology", "Year3", "Sem2"): [
        "Mammalian Anatomy & Physiology", "Biochemistry",
        "Introduction to Ethnobiology", "Virology",
        "Plant Anatomy and Physiology", "Principles of Ecology",
    ],
    ("Natural Sciences", "Biology", "Year4", "Sem1"): [
        "Aquatic Science and Wetland Management",
        "Wild life Ecology and Management",
        "Research Methods and Reporting in Science", "Internship",
        "Applied Microbiology", "Molecular Biology", "Entrepreneurship", "Elective I",
    ],
    ("Natural Sciences", "Biology", "Year4", "Sem2"): [
        "Senior Project", "Principles of Taxonomy",
        "Fundamentals of Biotechnology", "Introduction to Immunology",
        "Fisheries and Aquaculture", "Evolution",
        "Conservation and management of Natural Resources",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # NATURAL SCIENCES — CHEMISTRY
    # ══════════════════════════════════════════════════════════════════════════
    ("Natural Sciences", "Chemistry", "Year2", "Sem1"): [
        "Analytical Chemistry", "Practical Analytical Chemistry",
        "Organic Chemistry I", "Practical Organic Chemistry I",
        "Mechanics and Heat for Chemists", "Inclusiveness",
        "Applied Mathematics I for Chemists", "Introductory Statistics",
    ],
    ("Natural Sciences", "Chemistry", "Year2", "Sem2"): [
        "Inorganic Chemistry I", "Instrumental Analysis I",
        "Practical Instrumental Analysis I", "Chemical Thermodynamics",
        "Global tends", "Electricity and Magnetism for Chemists",
        "Applied Mathematics II for Chemists",
    ],
    ("Natural Sciences", "Chemistry", "Year3", "Sem1"): [
        "Organic Chemistry II", "Practical Organic Chemistry II",
        "Inorganic Chemistry II", "Practical Inorganic Chemistry I",
        "Kinetics and Electrochemistry", "Practical physical Chemistry I",
        "Industrial Chemistry I", "Applied Mathematics III for Chemists",
    ],
    ("Natural Sciences", "Chemistry", "Year3", "Sem2"): [
        "Environmental Chemistry and Toxicology", "Instrumental Analysis II",
        "Practical Instrumental Analysis II", "Inorganic Chemistry III",
        "Practical Inorganic Chemistry II", "Industrial Chemistry II",
        "Industrial attachment", "Research Method and Scientific Writing",
    ],
    ("Natural Sciences", "Chemistry", "Year4", "Sem1"): [
        "Physical Organic Chemistry", "Practical Organic Chemistry III",
        "Quantum Chemistry", "Chemistry of Consumer Products", "Elective I",
        "Entrepreneurship and Business Development", "Elective II",
    ],
    ("Natural Sciences", "Chemistry", "Year4", "Sem2"): [
        "Statistical Thermodynamics and Surface Chemistry",
        "Practical physical Chemistry II", "Real Sample Analysis",
        "Introduction to Material Chemistry", "Biochemistry", "Student Senior Project",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # NATURAL SCIENCES — GEOLOGY
    # ══════════════════════════════════════════════════════════════════════════
    ("Natural Sciences", "Geology", "Year2", "Sem1"): [
        "General Geology", "Geomorphology", "Paleontology", "Practical Paleontology",
        "Crystallography & Mineral optics", "Practical Crystallography & Mineral optics",
        "Inclusiveness", "Applied Mathematics I", "Introduction to Computer Science",
    ],
    ("Natural Sciences", "Geology", "Year2", "Sem2"): [
        "Stratigraphy & Earth History", "Mineralogy", "Practical Mineralogy",
        "Structural Geology", "Practical Structural Geology", "Tectonics",
        "Applied Mathematics II", "Sedimentary Petrology", "Pract. Sedimentary Petrology",
    ],
    ("Natural Sciences", "Geology", "Year3", "Sem1"): [
        "Mapping Techniques and Report writing", "Remote Sensing & GIS",
        "Principles of Hydrogeology", "Physical Chemistry",
        "Igneous Petrology", "Pract. Igneous Petrology",
        "Mapping Sedimentary Terrain", "Geophysics",
    ],
    ("Natural Sciences", "Geology", "Year3", "Sem2"): [
        "Geochemistry", "Mapping Igneous Terrain", "Exploration Geophysics",
        "Statistics for Geologists", "Groundwater Exploration & Development",
        "Petroleum & Coal Geology", "Metamorphic Petrology",
        "Pract. Metamorphic Petrology",
    ],
    ("Natural Sciences", "Geology", "Year4", "Sem1"): [
        "Global trends", "Economic Geology", "Environmental Geology",
        "Pract. Economic Geology", "Fundamentals of Soil & Rock Mechanics",
        "Elective I", "Mapping Metamorphic Terrain", "Research method in Geoscience",
    ],
    ("Natural Sciences", "Geology", "Year4", "Sem2"): [
        "Mineral Exploration & Mining", "Volcanology & Geothermal Resources",
        "Entrepreneurship & Business Development",
        "Geology & Geologic Resources of Ethiopia",
        "Senior project", "Engineering Geology", "Elective II",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # NATURAL SCIENCES — MATHEMATICS
    # ══════════════════════════════════════════════════════════════════════════
    ("Natural Sciences", "Mathematics", "Year2", "Sem1"): [
        "Fundamental Concepts of Algebra", "Calculus I",
        "Introduction to statistics", "Introduction to Computer Sciences",
        "Linear Algebra I", "Global Trends",
    ],
    ("Natural Sciences", "Mathematics", "Year2", "Sem2"): [
        "Introduction to Combinatorics and Graph Theory", "Calculus II",
        "Inclusivness", "Fundamental concepts of Geometry",
        "Fundamentals of Programming", "Probability Theory",
    ],
    ("Natural Sciences", "Mathematics", "Year3", "Sem1"): [
        "Transformation Geometry", "Number Theory",
        "Calculus of Functions of Several Variables",
        "Mechanics and Heat", "Experimental Physics I", "Linear Algebra II",
    ],
    ("Natural Sciences", "Mathematics", "Year3", "Sem2"): [
        "Numerical Analysis I", "Linear Optimization",
        "Introduction to Mathematical Software", "Financial Mathematics I",
        "Modern Algebra I", "Ordinary Differential Equation",
    ],
    ("Natural Sciences", "Mathematics", "Year4", "Sem1"): [
        "Introduction to Research Methods",
        "Calculus of Function of Complex Variables",
        "Partial Differential Equations",
        "Advanced calculus of one variable", "Elective I",
        "Entrepreneurship and Business Development",
    ],
    ("Natural Sciences", "Mathematics", "Year4", "Sem2"): [
        "Introduction to Topology", "Mathematical Modeling",
        "Undergraduate Mathematics research/Project", "Elective II",
        "Fundamentals of Database system", "Elective III",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # NATURAL SCIENCES — PHYSICS
    # ══════════════════════════════════════════════════════════════════════════
    ("Natural Sciences", "Physics", "Year2", "Sem1"): [
        "Calculus I", "Experiments in mechanics", "Introduction to Statistics",
        "Introduction to computer Science", "General Geology",
        "Global Trends", "Mechanics",
    ],
    ("Natural Sciences", "Physics", "Year2", "Sem2"): [
        "Calculus II", "Electromagnetism", "Experiments in electromagnetism",
        "Modern Physics", "Inclusiveness", "Fluid and Thermal Physics",
        "Experiments in Fluid and Thermal Physics",
    ],
    ("Natural Sciences", "Physics", "Year3", "Sem1"): [
        "Classical Mechanics", "Experiments in Oscillations and Waves",
        "Fundamentals of programming", "Introduction to relativity",
        "Linear algebra", "Mathematical Methods of physics I",
        "Physics of oscillations and Waves",
    ],
    ("Natural Sciences", "Physics", "Year3", "Sem2"): [
        "Electrodynamics I", "Electronics", "Experiments in Electronics",
        "Mathematical methods of physics II", "Nuclear physics",
        "Quantum mechanics I", "General Astronomy",
    ],
    ("Natural Sciences", "Physics", "Year4", "Sem1"): [
        "Computational physics", "Introduction to Condensed matter physics",
        "Electrodynamics II", "Entrepreneurship and Business Development",
        "Quantum mechanics II", "Statistical physics", "Research method",
    ],
    ("Natural Sciences", "Physics", "Year4", "Sem2"): [
        "Advanced experimental physics", "Elective",
        "Introduction to Laser and Optics", "Introduction to Nano Physics",
        "Senior research project/thesis",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # NATURAL SCIENCES — SPORT SCIENCE
    # ══════════════════════════════════════════════════════════════════════════
    ("Natural Sciences", "Sport Science", "Year2", "Sem1"): [
        "History & Concepts of Physical Education Sports",
        "Intr. to Sport Psychology", "Human Anatomy", "Athletics I",
        "Basic Gymnastics", "Inclusiveness",
    ],
    ("Natural Sciences", "Sport Science", "Year2", "Sem2"): [
        "Introduction to Sport sociology", "Apparatus Gymnastics",
        "Volleyball", "Athletics II", "Introduction to statistics",
        "Global trends", "Human Physiology",
    ],
    ("Natural Sciences", "Sport Science", "Year3", "Sem1"): [
        "Biochemistry", "Sport Journalism", "Exercise Physiology",
        "Racket Sports", "Measurement & Evaluation in Sports", "Football",
    ],
    ("Natural Sciences", "Sport Science", "Year3", "Sem2"): [
        "Health & Fitness", "Basket Ball", "Research Methods in Sport Science",
        "Sport Medicine", "Ethiopia Cultural Games & Sports", "Sport Nutrition",
    ],
    ("Natural Sciences", "Sport Science", "Year4", "Sem1"): [
        "Intro. to Structure of Coaching",
        "Fundamental of Massage & Therapeutic Exercise",
        "Self Defense & Sport Ethics", "Kinesiology", "Handball",
        "Entrepreneurships and business development",
    ],
    ("Natural Sciences", "Sport Science", "Year4", "Sem2"): [
        "Introduction to Adapted physical activity Sports", "Elective Course",
        "Swimming & Recreational Activities", "Introduction to Sport Management",
        "Senior Essay",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # NATURAL SCIENCES — STATISTICS
    # ══════════════════════════════════════════════════════════════════════════
    ("Natural Sciences", "Statistics", "Year2", "Sem1"): [
        "Calculus I", "Linear Algebra I",
        "Introduction to Computer science and application",
        "Basic Statistics", "Inclusiveness", "Global trends",
    ],
    ("Natural Sciences", "Statistics", "Year2", "Sem2"): [
        "Fundamentals of Programming", "Calculus for Statistics",
        "Linear Algebra II", "Statistical Methods",
        "Microeconomics", "Introduction to Probability Theory",
    ],
    ("Natural Sciences", "Statistics", "Year3", "Sem1"): [
        "Sampling Theory", "Regression analysis",
        "Fundamentals of Database Systems", "Statistical Computing I",
        "Numerical Methods for Statistics", "Macroeconomics",
    ],
    ("Natural Sciences", "Statistics", "Year3", "Sem2"): [
        "Statistical Computing II",
        "Research Method and Sample Survey Practice",
        "Design and Analysis of Experiments", "Categorical Data Analysis",
        "Time Series Analysis", "Entrepreneurship",
    ],
    ("Natural Sciences", "Statistics", "Year4", "Sem1"): [
        "Statistical Theory of Distributions", "Demography", "Econometrics",
        "Statistical Quality Control", "Elective",
        "Project I: Proposal writing", "Practical Attachments",
    ],
    ("Natural Sciences", "Statistics", "Year4", "Sem2"): [
        "Statistical Inference", "Biostatistics and Epidemiology",
        "Project II: Research Project in Statistics",
        "Introduction to Multivariate Methods", "Elective",
        "Social and Economic Statistics",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # NATURAL SCIENCES — ENVIRONMENTAL SCIENCE (Natural Sciences faculty)
    # (Note: there is also an Env Science under Agriculture below)
    # The Natural Sciences faculty doesn't list Environmental Science in the
    # PDF stream data but has it in FACULTIES. Leave without predefined data
    # so custom courses can be added.
    # ══════════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════════
    # HEALTH SCIENCES — Year 1 Common
    # ══════════════════════════════════════════════════════════════════════════
    ("Health Sciences", "", "Year1", "Sem1"): [
        "Communicative English Skills I", "General Physics", "General Psychology",
        "Mathematics for Natural Science", "Critical Thinking", "Physical fitness",
        "Geography of Ethiopia & the Horn",
    ],
    ("Health Sciences", "", "Year1", "Sem2"): [
        "Communicative English Skills II", "Social Anthropology", "General Biology",
        "History of Ethiopia & the Horn", "Introduction to emerging Technologies",
        "Moral and Civic Education", "General Chemistry",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # HEALTH SCIENCES — ENVIRONMENTAL HEALTH
    # ══════════════════════════════════════════════════════════════════════════
    ("Health Sciences", "Environmental Health", "Year2", "Sem1"): [
        "Analytical Chemistry", "Organic Chemistry", "Human Anatomy",
        "Human Physiology", "Medical microbiology", "Medical parasitology",
        "Introduction to Environmental Health", "Global trend",
        "Ecology", "First Aid and Accident prevention",
    ],
    ("Health Sciences", "Environmental Health", "Year2", "Sem2"): [
        "Biochemistry", "Communicable disease control", "Community Nutrition",
        "Family Health", "Biostatistics", "Introduction to GIS and remote sensing",
        "Surveying and mapping", "Applied Engineering Drawing",
    ],
    ("Health Sciences", "Environmental Health", "Year3", "Sem1"): [
        "Medical Entomology and Vector control", "Health education and promotion",
        "Food Safety management", "Residential and institutional health",
        "Sanitation System and Technology", "Sanitary Construction",
        "Water Supply", "Water quality management", "CBTP I", "CBTP II",
    ],
    ("Health Sciences", "Environmental Health", "Year3", "Sem2"): [
        "Research Method", "Waste water management and engineering",
        "Air pollution management", "Climate change and Health",
        "Environmental Sampling and Quality analysis", "Solid Waste Management",
        "Hazardous Waste Management", "Health informatics", "CBTP III",
    ],
    ("Health Sciences", "Environmental Health", "Year4", "Sem1"): [
        "One Health", "Infection prevention and control",
        "Environmental Toxicology", "Health emergency and Disaster Risk management",
        "Health Economics", "Occupational health and safety",
        "Project development and management", "Inclusiveness", "Entrepreneurship",
    ],
    ("Health Sciences", "Environmental Health", "Year4", "Sem2"): [
        "Health Service Management", "Environmental and social impact assessment",
        "Environmental health professional ethics", "Student Research project",
        "Professional practice", "Professional Apprenticeship", "TTP",
        "Comprehensive Examination",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # HEALTH SCIENCES — MEDICAL LABORATORY SCIENCE
    # ══════════════════════════════════════════════════════════════════════════
    ("Health Sciences", "Medical Laboratory Science", "Year2", "Sem1"): [
        "Genetics", "Molecular biology", "Anatomy", "Physiology",
        "Biochemistry", "Pharmacology", "Organic chemistry",
        "Analytical Chemistry", "Determinants of health",
    ],
    ("Health Sciences", "Medical Laboratory Science", "Year2", "Sem2"): [
        "Introduction to medical laboratory sciences", "Instrumentation",
        "First aid", "professional ethics", "Medical Parasitology",
        "Vector biology", "Clinical attachment 1", "Measurement of Health and Disease",
    ],
    ("Health Sciences", "Medical Laboratory Science", "Year3", "Sem1"): [
        "Immunology", "Serology", "Hematology", "Immunohematology",
        "Inclusiveness", "Global trend", "Health Promotion and Disease Prevention",
        "Histopathology",
    ],
    ("Health Sciences", "Medical Laboratory Science", "Year3", "Sem2"): [
        "Medical Bacteriology", "Public Health Microbiology", "Medical Virology",
        "Medical mycology", "Health Service Management",
        "Community Based Training Program (CBTP)", "Clinical Laboratory Attachment II",
    ],
    ("Health Sciences", "Medical Laboratory Science", "Year4", "Sem1"): [
        "Clinical Chemistry", "Toxin Analysis", "Urine and Body Fluid Analysis",
        "Quality Assurance in Medical Laboratory", "Health Laboratory Management",
        "Research Methodology", "Student Research Proposal", "Entrepreneurship",
    ],
    ("Health Sciences", "Medical Laboratory Science", "Year4", "Sem2"): [
        "Health informatics", "Advanced Laboratory Attachment",
        "Clinical Laboratory Attachment III", "laboratory internship",
        "student research project", "Team Training Program (TTP)",
        "Comprehensive Examination",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # HEALTH SCIENCES — MIDWIFERY
    # ══════════════════════════════════════════════════════════════════════════
    ("Health Sciences", "Midwifery", "Year2", "Sem1"): [
        "Inclusiveness", "Foundation of Midwifery I",
        "Entrepreneurship", "Health Promotion and Disease Prevention",
    ],
    ("Health Sciences", "Midwifery", "Year2", "Sem2"): [
        "Foundation of Midwifery II", "Preconception Care", "Antenatal Care",
    ],
    ("Health Sciences", "Midwifery", "Year3", "Sem1"): [
        "Labor and Delivery", "Postnatal Care", "Family Planning",
    ],
    ("Health Sciences", "Midwifery", "Year3", "Sem2"): [
        "Newborn Care", "Under Five Child Health", "Gynecology",
    ],
    ("Health Sciences", "Midwifery", "Year4", "Sem1"): [
        "Health Policy Management", "Measurement of Health and Disease",
        "Research Method", "Antenatal Care Internship",
        "Labour and Delivery Internship", "Postnatal Care Internship",
        "Family Planning Internship",
    ],
    ("Health Sciences", "Midwifery", "Year4", "Sem2"): [
        "Gynecology Internship", "Pediatrics and Neonatology Internship",
        "Research Project", "Team Training Program (TTP)",
        "Community Based Training Program (CBTP)",
        "Final Comprehensive Qualification Exam",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # HEALTH SCIENCES — NURSING (has its own Year 1)
    # ══════════════════════════════════════════════════════════════════════════
    ("Health Sciences", "Nursing", "Year1", "Sem1"): [
        "Communicative English skills 1", "General physics", "General psychology",
        "Mathematics for natural science", "Critical thinking",
        "Geography of Ethiopia and the horn", "Physical fitness",
        "History of Ethiopia and the horn",
    ],
    ("Health Sciences", "Nursing", "Year1", "Sem2"): [
        "Communicative English skills 2", "General Biology", "General chemistry",
        "Moral and civics Education", "Biomedical science 1", "Foundation of nursing 1",
    ],
    ("Health Sciences", "Nursing", "Year2", "Sem1"): [
        "Inclusiveness", "Entrepreneurship", "Determinant of health",
        "Biomedical science 2", "Foundation of nursing 2",
    ],
    ("Health Sciences", "Nursing", "Year2", "Sem2"): [
        "Social anthropology", "Health promotion & disease prevention",
        "Measurement of health & disease", "Medical surgical nursing 1", "CBTP",
    ],
    ("Health Sciences", "Nursing", "Year3", "Sem1"): [
        "Medical-surgical nursing 2", "Maternity & reproductive health nursing",
        "Pediatrics & child health nursing", "Global Trends", "Mental health nursing",
    ],
    ("Health Sciences", "Nursing", "Year3", "Sem2"): [
        "Introduction to emerging technology", "Economics",
        "Pediatrics & child health nursing", "Global Trends", "Mental health nursing",
    ],
    ("Health Sciences", "Nursing", "Year4", "Sem1"): [
        "Nursing education & curriculum development",
        "Nursing leadership & management", "Nursing research methods",
        "Pre-internship Exam", "Medical nursing internship",
    ],
    ("Health Sciences", "Nursing", "Year4", "Sem2"): [
        "Surgical nursing internship", "Maternity nursing internship",
        "Pediatrics nursing internship", "Student research project",
        "Team Training Program (TTP)", "Comprehensive qualification exam",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # HEALTH SCIENCES — PHARMACY (5 years)
    # ══════════════════════════════════════════════════════════════════════════
    ("Health Sciences", "Pharmacy", "Year2", "Sem1"): [
        "Pathology", "Human Physiology-II", "Chemistry of Natural products",
        "Biochemistry-I", "Biochemistry-II", "Microbiology",
        "Immunology & Parasitology", "Introduction to pharmacy",
        "Pharmaceutical calculations", "Economics",
    ],
    ("Health Sciences", "Pharmacy", "Year2", "Sem2"): [
        "Pharmacognosy", "Pharmacology-I", "Medicinal chemistry-I",
        "Integrated physical pharmacy and pharmaceutics-I",
        "Practical Integrated physical pharmacy and pharmaceutics-I",
        "Biostatistics", "Epidemiology", "Inclusiveness", "CBTP I",
    ],
    ("Health Sciences", "Pharmacy", "Year3", "Sem1"): [
        "Integrated physical pharmacy and pharmaceutics-II",
        "Practical Integrated physical pharmacy and pharmaceutics-II",
        "Pharmacology II", "Medicinal chemistry-II",
        "Integrated therapeutics-I", "Pharmaceutical analysis-I",
        "Physical assessment",
    ],
    ("Health Sciences", "Pharmacy", "Year3", "Sem2"): [
        "Biopharmaceutics and Clinical Pharmacokinetics",
        "Immunological and biological product", "Clinical toxicology",
        "Health service management and policies", "Integrated therapeutics-II",
        "Entrepreneurship", "Pharmaceutical analysis-II", "CBTP II",
    ],
    ("Health Sciences", "Pharmacy", "Year4", "Sem1"): [
        "Industrial pharmacy", "Introduction to Pharmacoeconomics",
        "Pharmaceutical Supply Chain management", "Integrated therapeutics-III",
        "Complementary and alternative medicine", "Drug informatics",
        "Pharmacy law and ethics",
    ],
    ("Health Sciences", "Pharmacy", "Year4", "Sem2"): [
        "Global Trends", "Medical supplies, equipment and reagents",
        "Pharmaceutical Marketing and promotion", "Integrated therapeutics-IV",
        "Pharmacy practice", "First aid", "Nutrition",
        "Professional elective course", "Research Methods", "CBTP-III",
    ],
    ("Health Sciences", "Pharmacy", "Year5", "Sem1"): [
        "Ambulatory care clerkship", "Drug information service clerkship",
        "Internal medicine clerkship", "Hospital pharmacy clerkship",
        "Pediatric clerkship",
    ],
    ("Health Sciences", "Pharmacy", "Year5", "Sem2"): [
        "Gyne, obstetrics and family planning clerkship",
        "Pharmaceutical Manufacturing clerkship",
        "Community pharmacy clerkship", "Elective attachment",
        "Directed study", "Team training program",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # HEALTH SCIENCES — PSYCHIATRY
    # ══════════════════════════════════════════════════════════════════════════
    ("Health Sciences", "Psychiatry", "Year2", "Sem1"): [
        "Health Informatics", "Inclusiveness",
        "SPH-1 determinants of health",
        "SPH-2 Health promotion and disease prevention",
        "Medical surgical module",
    ],
    ("Health Sciences", "Psychiatry", "Year2", "Sem2"): [
        "Maternal and Child Health", "Foundation of psychiatry I",
        "Foundation of psychiatry II",
    ],
    ("Health Sciences", "Psychiatry", "Year3", "Sem1"): [
        "Major psychiatry I", "Major psychiatry II",
        "Substance related addictive disorder", "Minor Psychiatry",
    ],
    ("Health Sciences", "Psychiatry", "Year3", "Sem2"): [
        "SPH 3-Health policy and management", "Community psychiatry",
        "Child & adolescent Psychiatry", "Qualification exam",
    ],
    ("Health Sciences", "Psychiatry", "Year4", "Sem1"): [
        "Psychiatry education & curriculum development",
        "SPH-4 Measurement of health and disease",
        "SPH-5 Research methodology", "Global Trend",
        "Consultation Liaison psychiatry", "Entrepreneurship",
        "Student Research project",
    ],
    ("Health Sciences", "Psychiatry", "Year4", "Sem2"): [
        "Community psychiatry Practice", "TTP",
        "Psychiatry professional internship", "Comprehensive Exit exam",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # HEALTH SCIENCES — PUBLIC HEALTH
    # ══════════════════════════════════════════════════════════════════════════
    ("Health Sciences", "Public Health", "Year2", "Sem1"): [
        "Introduction to Public Health", "Inclusiveness",
        "Embryology and Histology", "Human Anatomy", "Human Physiology",
        "Biochemistry", "Medical Microbiology", "Health Ethics and Legal Medicine",
    ],
    ("Health Sciences", "Public Health", "Year2", "Sem2"): [
        "Health Service Management", "Human Pathology", "Medical Parasitology",
        "Pharmacology", "Environmental Health and Ecology", "Human Nutrition",
        "Health Economics", "Disaster Prevention and Preparedness",
        "Reproductive Health", "Population and Development", "Global trends",
    ],
    ("Health Sciences", "Public Health", "Year3", "Sem1"): [
        "Biostatistics", "Epidemiology", "Health Informatics", "Research Methods",
        "Clinical Laboratory Methods", "Introduction to Nursing Art",
        "Health Education", "Community Based Training Program (CBTP)",
    ],
    ("Health Sciences", "Public Health", "Year3", "Sem2"): [
        "Physical Diagnosis", "Internal medicine I", "Surgery I",
        "Pediatrics I", "Gynecology and obstetrics I",
    ],
    ("Health Sciences", "Public Health", "Year4", "Sem1"): [
        "Dentistry", "Ear Nose and Throat", "Ophthalmology",
        "Diagnostic Radiology", "Dermatology", "Psychiatry",
        "Internal Medicine-II", "Surgery-II", "Pediatrics-II",
        "Obstetrics and gynecology-II",
    ],
    ("Health Sciences", "Public Health", "Year4", "Sem2"): [
        "Community Health Attachment (CHA)", "Team Training Program (TTP)",
        "Entrepreneurship", "Student Research Project",
        "Comprehensive Qualifying Examination",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # AGRICULTURE — Year 1 Common
    # ══════════════════════════════════════════════════════════════════════════
    ("Agriculture", "", "Year1", "Sem1"): [
        "Communicative English Skills I", "General Physics", "General Psychology",
        "Mathematics for Natural Science", "Critical Thinking", "Physical fitness",
        "Geography of Ethiopia & the Horn",
    ],
    ("Agriculture", "", "Year1", "Sem2"): [
        "Communicative English Skills II", "Social Anthropology", "General Biology",
        "History of Ethiopia & the Horn", "Introduction to emerging Technologies",
        "Moral and Civic Education", "General Chemistry",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # AGRICULTURE — AGRIBUSINESS & VALUE CHAIN MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════
    ("Agriculture", "Agribusiness & Value Chain Management", "Year2", "Sem1"): [
        "Introduction to Agribusiness Management", "Micro - Economics",
        "Principles of Accounting", "Business Law and Ethics",
        "Animal Production and Management", "Plant Production and Management",
        "Inclusiveness",
    ],
    ("Agriculture", "Agribusiness & Value Chain Management", "Year2", "Sem2"): [
        "Global tend", "Business Mathematics", "Value chain Analysis and Development",
        "Gender and Youth in Value chain", "Business Communication",
        "Macro - Economics", "Organization and Management of Cooperatives",
    ],
    ("Agriculture", "Agribusiness & Value Chain Management", "Year3", "Sem1"): [
        "Financial Management", "Cost and Management accounting",
        "International Agricultural Trade", "Agricultural Marketing",
        "Operational Research in Agribusiness",
        "Crop Value chain management", "Statistics for Agribusiness",
    ],
    ("Agriculture", "Agribusiness & Value Chain Management", "Year3", "Sem2"): [
        "Econometrics", "Research Method in Agribusiness and Value chain",
        "Computer Application in Agribusiness",
        "Livestock Value chain Management", "Farm management",
        "Operational Management", "Senior Research Proposal",
        "Seminar in Agribusiness",
    ],
    ("Agriculture", "Agribusiness & Value Chain Management", "Year4", "Sem1"): [
        "Entrepreneurship", "Change management", "Project Planning and Analysis",
        "Risk Management and Insurance in Agribusiness",
        "Logistics in Value chain", "Agricultural credit and finance",
        "Practical Attachment",
        "Tea, coffee and Timber products value chain management",
    ],
    ("Agriculture", "Agribusiness & Value Chain Management", "Year4", "Sem2"): [
        "E - commerce and Trade intelligence Management",
        "Climate change in Agribusiness", "Human Resource Management",
        "Organizational Behavior in Agribusiness",
        "Nutrition Sensitive Agriculture", "Agribusiness Policy and Strategy",
        "Senior Research Project",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # AGRICULTURE — AGRICULTURAL ECONOMICS
    # ══════════════════════════════════════════════════════════════════════════
    ("Agriculture", "Agricultural Economics", "Year2", "Sem1"): [
        "Microeconomics-I", "Introduction to Statistics",
        "Principles of Accounting", "Crop Production & Management",
        "Animal Production and Management", "Sociology", "Inclusiveness",
    ],
    ("Agriculture", "Agricultural Economics", "Year2", "Sem2"): [
        "Microeconomics II", "Macroeconomics-I", "Statistics for Economists",
        "Introduction to Agricultural Extension", "Natural Resource Management",
        "Farm Power and Machinery", "Gender and Youth in Development",
    ],
    ("Agriculture", "Agricultural Economics", "Year3", "Sem1"): [
        "Mathematics for Economists", "Macroeconomics II", "Farm Management",
        "Research Methods in Agricultural Economics",
        "Ethiopian Economy", "Seminar in Agricultural Economics", "Global Trends",
    ],
    ("Agriculture", "Agricultural Economics", "Year3", "Sem2"): [
        "Econometrics", "Computer Applications in Agricultural Economics",
        "Operations Research in Agricultural Economics",
        "Agricultural Credit and Finance",
        "Farming Systems and Livelihood Analysis",
        "History of Economic Thoughts", "Senior Research Proposal",
    ],
    ("Agriculture", "Agricultural Economics", "Year4", "Sem1"): [
        "International Trade", "Natural Resource and Environmental Economics",
        "Agribusiness Organizations and Cooperative Management",
        "Food and Agricultural Policy", "Practical Attachment",
        "Value Chain Analysis and Development", "Entrepreneurship",
    ],
    ("Agriculture", "Agricultural Economics", "Year4", "Sem2"): [
        "Agricultural Project Planning and Analysis", "Agricultural Marketing",
        "Institutional and Behavioral Economics", "Development Economics",
        "Economics of Climate Change", "Senior Research Project",
        "Nutrition Sensitive Agriculture",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # AGRICULTURE — ANIMAL SCIENCE
    # ══════════════════════════════════════════════════════════════════════════
    ("Agriculture", "Animal Science", "Year2", "Sem1"): [
        "Anatomy and Physiology of Farm Animals", "Biochemistry",
        "General Microbiology", "Introduction to Computer Application",
        "Fishery and Aquaculture", "Introduction to Soils",
        "Swine Production and Management",
    ],
    ("Agriculture", "Animal Science", "Year2", "Sem2"): [
        "Principle of Genetics", "Principle of Animal Nutrition",
        "Introduction to Statistics", "Inclusiveness",
        "Sheep and Goat Production and Management",
        "Forage and Pasture Production and Management",
        "Camel Production and Management",
    ],
    ("Agriculture", "Animal Science", "Year3", "Sem1"): [
        "Animal Breeding", "Reproductive Physiology and Artificial Insemination",
        "Applied Animal Nutrition", "Poultry Production and Hatchery Management",
        "Dairy Cattle Production and Management", "Global Trends",
        "Practical in Animal Science I",
    ],
    ("Agriculture", "Animal Science", "Year3", "Sem2"): [
        "Beef Cattle Production and Management",
        "Equine Production and Draft animals Management", "Biometry",
        "Research Methods in Animal Sciences", "Animal Biotechnology",
        "Range Ecology and Management", "Veterinary Parasitology",
        "Practical in Animal science II",
    ],
    ("Agriculture", "Animal Science", "Year4", "Sem1"): [
        "Practical Attachment", "Apiculture", "Sericulture",
        "Animal Behaviour and Welfare", "Entrepreneurship",
        "Hide and Skin Processing", "Animal Health and Disease Control",
        "Rural Sociology and Agricultural Extension", "Senior Seminar",
    ],
    ("Agriculture", "Animal Science", "Year4", "Sem2"): [
        "Food Hygiene and Veterinary Public Health",
        "Livestock Products Processing Technology",
        "Agricultural Project Planning and Analysis",
        "Livestock Economics and Marketing", "Nutrition Sensitive Agriculture",
        "Farm Stead Structure (E)", "Senior Research Project", "Farm Management",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # AGRICULTURE — ENVIRONMENTAL SCIENCE (Agriculture faculty)
    # ══════════════════════════════════════════════════════════════════════════
    ("Agriculture", "Environmental Science", "Year2", "Sem1"): [
        "Principles of Environmental Sciences", "General Ecology",
        "Environmental Economics", "Inclusiveness", "Environmental Physics",
        "Introduction to Statistics", "Computer Science and its Applications",
        "Introduction to Forestry",
    ],
    ("Agriculture", "Environmental Science", "Year2", "Sem2"): [
        "Fundamental Soil Sciences", "Climatology and Meteorology",
        "Environmental Chemistry", "Energy and Environment",
        "Environmental Hydrology", "Environmental Education and Communication",
        "GIS and Remote Sensing",
    ],
    ("Agriculture", "Environmental Science", "Year3", "Sem1"): [
        "Environmental Geology", "Principles of Environmental Informatics and Modeling",
        "Environmental Microbiology", "Environmental Sociology",
        "Environmental Degradation and Rehabilitation",
        "Solid and Hazardous Waste Management",
        "Climate Change Adaptation and Mitigation", "Surveying and Mapping",
    ],
    ("Agriculture", "Environmental Science", "Year3", "Sem2"): [
        "Land Evaluation and Land Use Planning",
        "Integrated Watershed Management",
        "Environment, Gender and Development", "Research Methods",
        "Water and Wastewater Treatment", "Environmental Toxicology",
        "Community Based Practical Education",
        "Industrial and Urban Environmental Management",
    ],
    ("Agriculture", "Environmental Science", "Year4", "Sem1"): [
        "Environmental Disaster and Risk Management",
        "Environmental and Social Impact Assessment",
        "Environmental Biotechnology and Biosafety",
        "Limnology and Wetland Management",
        "Biodiversity Conservation and Management", "Global Trends",
        "Senior Seminar", "Environmental Sampling and Analysis",
    ],
    ("Agriculture", "Environmental Science", "Year4", "Sem2"): [
        "Environmental Landscaping and Design",
        "Environmental Policy and Laws",
        "Environmental Management Systems and Auditing",
        "Senior Research Project",
        "Project Planning, Analysis and Management", "Entrepreneurship",
        "Environmental Pollution Control and Management", "Environmental Health",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # AGRICULTURE — FORESTRY
    # ══════════════════════════════════════════════════════════════════════════
    ("Agriculture", "Forestry", "Year2", "Sem1"): [
        "Global trends", "Inclusiveness", "Introduction to Statistics",
        "Introduction to Information & Communication Technology",
        "Physiology of woody plants", "General Ecology",
        "Forest seed and nursery technology",
    ],
    ("Agriculture", "Forestry", "Year2", "Sem2"): [
        "Dendrology", "Forest Ecology", "Economics",
        "Wood Structure & properties", "Remote sensing & GIS",
        "Forest surveying & mapping", "Biodiversity conservation",
    ],
    ("Agriculture", "Forestry", "Year3", "Sem1"): [
        "Mensuration and Inventory",
        "Forest Ecosystem rehabilitation and restoration",
        "Soil &water conservation",
        "Silviculture of Natural Forest and Wood Land",
        "Fundamental and Forest Soil Science",
        "Tree Genetics and Improvement", "Climatology & Forest Influence",
    ],
    ("Agriculture", "Forestry", "Year3", "Sem2"): [
        "Research method", "Land use planning & watershed management",
        "Forest Economics", "Forest Biometry", "Internship/Practical education",
        "Plantation establishment & management",
        "Forest road construction & maintenance",
    ],
    ("Agriculture", "Forestry", "Year4", "Sem1"): [
        "Forest harvesting", "Wood processing", "Entrepreneurship",
        "Bioenergy Technology", "Non timber Forest products",
        "Forest Policy & law", "Forest Protection", "Senior seminar",
    ],
    ("Agriculture", "Forestry", "Year4", "Sem2"): [
        "Agro-forestry Systems & Technology",
        "Rural Sociology and Extension", "Project Planning and Management",
        "Forest Management", "Wild life management",
        "Forest Business Management", "Participatory Forest Management",
        "Research project",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # AGRICULTURE — HORTICULTURE
    # ══════════════════════════════════════════════════════════════════════════
    ("Agriculture", "Horticulture", "Year2", "Sem1"): [
        "Agro-meteorology", "Global Trends", "Agricultural Microbiology",
        "Inclusiveness", "Plant Anatomy, Morphology and Taxonomy",
        "Plant Physiology", "Introduction to Soil Science", "Principles of Genetics",
    ],
    ("Agriculture", "Horticulture", "Year2", "Sem2"): [
        "Soil Fertility and Plant Nutrition", "Plant Biochemistry",
        "Principles and Practices of Plant Propagation",
        "Introduction to Statistics", "Plant Breeding",
        "Principles and Practices of Irrigation", "Practical Horticulture",
    ],
    ("Agriculture", "Horticulture", "Year3", "Sem1"): [
        "Soil and Water Conservation", "Agricultural Entomology",
        "Introduction to Plant Biotechnology",
        "Horticultural Seed Science and Technology",
        "Principles, Design and Analysis of Agricultural Experiments",
        "Plant Pathology",
        "Principles and Practices of Protected Horticulture",
    ],
    ("Agriculture", "Horticulture", "Year3", "Sem2"): [
        "Urban and Peri-urban Horticulture",
        "Vegetable Crops Production and Management",
        "Ornamental Plants Production and Management",
        "Weeds and their Management", "Farm Machinery and Implements",
        "Tropical Fruit Crops Production and Management",
        "Research Methods in Horticulture", "Plant Ecology",
        "Practical Attachment",
    ],
    ("Agriculture", "Horticulture", "Year4", "Sem1"): [
        "Root and Tuber Crops Production and Management",
        "Coffee Production, Processing and Quality Control",
        "Sub-tropical and Temperate Fruit Crops Production and Management",
        "Management of Horticultural Crops Diseases and Arthropod Pests",
        "Spices, Herbs and Medicinal Plants Production and Processing",
        "Tea Production and Processing", "Landscape Designing",
        "Senior seminar", "Senior Research Project Proposal",
    ],
    ("Agriculture", "Horticulture", "Year4", "Sem2"): [
        "Postharvest Physiology and Handling of Horticultural Products",
        "Entrepreneurship and Business Development",
        "Nutrition Sensitive Agriculture",
        "Rural Sociology and Agricultural Extension",
        "Marketing of Horticultural Crops", "Farm Management",
        "Senior Research Project",
        "Food Safety, Quality and Processing of Horticultural Crops",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # AGRICULTURE — NATURAL RESOURCE MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════
    ("Agriculture", "Natural Resource Management", "Year2", "Sem1"): [
        "Introductory Soils", "Introduction to Ecology",
        "General Microbiology", "Inclusiveness",
        "Principle of Environmental Sciences", "Introduction to Statistics",
        "Computer Science and Its Application",
    ],
    ("Agriculture", "Natural Resource Management", "Year2", "Sem2"): [
        "Integrated Soil Fertility Management",
        "Biodiversity Conservation and Management",
        "Nursery Establishment & Plantation Management",
        "Plant Taxonomy", "Natural Resource and Environmental Economics",
        "Environment, Gender & Development",
        "Climatology and Agro-meteorology",
    ],
    ("Agriculture", "Natural Resource Management", "Year3", "Sem1"): [
        "Wildlife Ecology and Management",
        "Ecotourism Principles and Approaches",
        "Climate Change Adaptation and Mitigation",
        "GIS and Remote Sensing", "Sustainable Forest Management",
        "Range Land Ecology and Management", "Hydrology",
        "Sustainable Agricultural Systems",
    ],
    ("Agriculture", "Natural Resource Management", "Year3", "Sem2"): [
        "Energy and Environment", "Non-timber Forest Products and Management",
        "Limnology and Wetland Management",
        "Land Degradation and Rehabilitation", "Surveying and Mapping",
        "Soil and Water Management",
        "Water Resources Planning, Development and Management",
        "Community Based Practical Education",
    ],
    ("Agriculture", "Natural Resource Management", "Year4", "Sem1"): [
        "Integrated Watershed Management",
        "Project Planning, Analysis and Management",
        "Principles of Irrigation and Drainage", "Research Methods",
        "Natural Resources Policy and Law", "Global Trends",
        "Agro-forestry Systems and Practices", "Senior Seminar",
    ],
    ("Agriculture", "Natural Resource Management", "Year4", "Sem2"): [
        "Land Evaluation and Land Use Planning",
        "Environmental and Social Impact Assessment",
        "Rural Sociology and Natural Resources Management Extension",
        "Nutrition Sensitive Agriculture", "Senior Research Project",
        "Entrepreneurship", "Natural Resources and Conflict Management",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # AGRICULTURE — PLANT SCIENCE
    # ══════════════════════════════════════════════════════════════════════════
    ("Agriculture", "Plant Science", "Year2", "Sem1"): [
        "Plant Biochemistry", "Plant Morphology and Anatomy",
        "Agricultural Microbiology",
        "Introduction to Computer and its application",
        "Climatology and Agrometeorology",
        "Introduction to Forestry and Agro-forestry",
        "Introductory Soils", "Inclusiveness",
    ],
    ("Agriculture", "Plant Science", "Year2", "Sem2"): [
        "Principles of Genetics", "Plant Taxonomy", "Plant Ecology",
        "Introduction to Statistics", "GIS and Remote Sensing (E)",
        "Introduction to Animal sciences (E)", "Farm Machinery and Implements",
    ],
    ("Agriculture", "Plant Science", "Year3", "Sem1"): [
        "Plant Breeding", "Plant Physiology", "Agricultural Entomology",
        "Plant Pathology",
        "Principles, Design and Analysis of Agricultural Experiments",
        "Soil and Water Conservation", "Global Trends",
    ],
    ("Agriculture", "Plant Science", "Year3", "Sem2"): [
        "Research Methods in Plant Sciences",
        "Fruit Crops Production and Processing",
        "Weeds and Their Management", "Seed Science and Technology",
        "Floriculture and Landscaping", "Introduction to Plant Biotechnology",
        "Soil Fertility and Plant Nutrition",
        "Rural Sociology and Agricultural Extension",
        "Practical Plant Sciences",
    ],
    ("Agriculture", "Plant Science", "Year4", "Sem1"): [
        "Coffee and Tea Production and Processing",
        "Spices, Aromatic and Medicinal Plants Production and Processing",
        "Vegetable Crops Production and Management",
        "Industrial Crops Production and Processing",
        "Field Crops Production and Management",
        "Principles and Practices of Irrigation",
        "Entrepreneurship and Small Business Management",
        "Practical Attachment in Plant Sciences",
        "Senior Research Proposal", "Senior Seminar",
    ],
    ("Agriculture", "Plant Science", "Year4", "Sem2"): [
        "Post-harvest Handling and Value Addition of Grain Crops",
        "Post-Harvest Physiology and Handling of Horticultural Crops",
        "Agro-chemicals and Their Application (E)",
        "Nutrition Sensitive Agriculture",
        "Management of Crop Diseases and Insect Pests of Economic Importance",
        "Dryland Agriculture (E)", "Farm Management",
        "Agricultural Project Planning, Evaluation and Analysis",
        "Senior Research Report",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # AGRICULTURE — VETERINARY SCIENCE
    # ══════════════════════════════════════════════════════════════════════════
    ("Agriculture", "Veterinary Science", "Year2", "Sem1"): [
        "Inclusiveness", "Veterinary Biochemistry", "Veterinary Gross Anatomy",
        "Veterinary physiology", "Veterinary Histology", "Veterinary Embryology",
        "Sheep, goat and swine production", "Animals Genetics and Breeding",
    ],
    ("Agriculture", "Veterinary Science", "Year2", "Sem2"): [
        "Introduction to Molecular Biology", "Veterinary Parasitology",
        "Veterinary Microbiology", "Veterinary Immunology",
        "Animal feeds and nutrition", "Dairy and beef cattle production",
        "Veterinary Pathology",
    ],
    ("Agriculture", "Veterinary Science", "Year3", "Sem1"): [
        "Veterinary Pharmacology and therapeutics",
        "Poultry Production and Health", "Camel Production and Health",
        "Veterinary General Medicine", "Veterinary clinical diagnosis",
        "Working Animal Management", "Global Trends",
        "Introduction to Computer Application",
    ],
    ("Agriculture", "Veterinary Science", "Year3", "Sem2"): [
        "Veterinary Toxicology", "Large Animal Medicine",
        "Small animal medicine", "Veterinary surgery and diagnostic imaging",
        "Veterinary clinical practice I",
        "Animal health extension and pastoralism",
        "Vet. Ethics and animal welfare",
        "Veterinary Gynecology and reproductive technology",
        "Apiculture and bee disease",
    ],
    ("Agriculture", "Veterinary Science", "Year4", "Sem1"): [
        "Fisheries and fish diseases",
        "Biostatistics and Research Methodology",
        "Veterinary Clinical Pathology", "Veterinary clinical practice II",
        "Epidemiology and Preventive Medicine", "Entrepreneurship",
        "Animal Health Economics", "Veterinary public health",
    ],
    ("Agriculture", "Veterinary Science", "Year4", "Sem2"): [
        "Seminar on Current Topics in Veterinary Science 1",
        "Senior Research Project 2", "Veterinary Clinical Experience 3",
        "Veterinary Laboratory Work Experience 3",
        "Farm Experience 1", "Experience in Veterinary Public Health 1",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — Year 1 Common
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "", "Year1", "Sem1"): [
        "Communicative English Skills I", "Economics", "General Psychology",
        "Mathematics for Social Sciences", "Critical Thinking", "Physical fitness",
        "Geography of Ethiopia & the Horn",
    ],
    ("Social Sciences & Humanities", "", "Year1", "Sem2"): [
        "Communicative English Skills II", "Social Anthropology",
        "Entrepreneurship", "History of Ethiopia & the Horn",
        "Introduction to emerging Technologies", "Moral and Civic Education",
        "Global Trends",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — ACCOUNTING & FINANCE
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "Accounting & Finance", "Year2", "Sem1"): [
        "Fundamentals of Accounting I", "Introduction to Management",
        "Business Mathematics", "Macroeconomics",
        "Basic Statistics", "Fundamentals of Information Systems",
    ],
    ("Social Sciences & Humanities", "Accounting & Finance", "Year2", "Sem2"): [
        "Fundamentals of Accounting II", "Business Statistics",
        "Principles of Marketing", "Risk Management & Insurance",
        "Contemporary Business Communication", "Business Law",
    ],
    ("Social Sciences & Humanities", "Accounting & Finance", "Year3", "Sem1"): [
        "Intermediate Financial Accounting I",
        "Cost & Management Accounting I",
        "Research Methods in Accounting & Finance",
        "Financial Management I",
        "Accounting for Public sector and civil society",
        "Financial Institutions & Markets",
    ],
    ("Social Sciences & Humanities", "Accounting & Finance", "Year3", "Sem2"): [
        "Intermediate Financial Accounting II",
        "Cost & Management Accounting II", "Financial Management II",
        "Financial Modeling", "Econometrics for finance", "Operations Research",
    ],
    ("Social Sciences & Humanities", "Accounting & Finance", "Year4", "Sem1"): [
        "Advanced Financial Accounting I", "Auditing Principles & Practices I",
        "Operations Management", "Internship",
        "Accounting Information Systems", "Public Finance & Taxation",
        "Investment Analysis and Portfolio Management", "Senior Research Project I",
    ],
    ("Social Sciences & Humanities", "Accounting & Finance", "Year4", "Sem2"): [
        "Advanced Financial Accounting II", "Strategic Management",
        "Auditing Principles and Practices II",
        "Project Analysis & Evaluation", "Senior Research Project II",
        "Accounting Software Applications",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — COOPERATIVE BUSINESS MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "Cooperative Business Management", "Year2", "Sem1"): [
        "Cooperative Theory and Practice", "Introduction to management",
        "Basic Statistics", "Fundamentals of Accounting I",
        "Intermediate Economics", "Business Mathematics",
    ],
    ("Social Sciences & Humanities", "Cooperative Business Management", "Year2", "Sem2"): [
        "Cooperative Organization and Management", "Cooperative Legal System",
        "Business Statistics", "Business Communication",
        "Fundamentals of Accounting II", "Business Law",
        "Introduction to computer application",
    ],
    ("Social Sciences & Humanities", "Cooperative Business Management", "Year3", "Sem1"): [
        "Ethiopian Cooperative Development and Extension",
        "Participatory Approaches in cooperatives",
        "Management of Agricultural and Nonagricultural Cooperatives",
        "Introduction to Econometrics", "Introduction to Sociology",
        "Financial Management-I", "Human Resource Management",
    ],
    ("Social Sciences & Humanities", "Cooperative Business Management", "Year3", "Sem2"): [
        "Gender and Development in Cooperatives",
        "Agribusiness in Cooperatives", "Research Methods in Cooperatives",
        "Principles of Marketing", "Materials Management",
        "Financial Management-II", "Organizational Behaviors",
    ],
    ("Social Sciences & Humanities", "Cooperative Business Management", "Year4", "Sem1"): [
        "Project Management", "Strategic Management",
        "Risk Management and Insurance", "Operations Research",
        "Cost and Management Accounting-I", "Senior Research Project Proposal",
        "Practical Attachment Program in Coops (PAP)",
    ],
    ("Social Sciences & Humanities", "Cooperative Business Management", "Year4", "Sem2"): [
        "Operations Management", "Advanced Entrepreneurship and Business Dev't",
        "Financial Cooperatives Administration",
        "Cost and Management Accounting-II",
        "Management Information System", "International Marketing",
        "Senior Research Project",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — ECONOMICS
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "Economics", "Year2", "Sem1"): [
        "Calculus for Economists", "Microeconomics I", "Macroeconomics I",
        "Introduction to statistics", "Fundamental of Accounting I",
        "Basic computer skill of Microsoft",
    ],
    ("Social Sciences & Humanities", "Economics", "Year2", "Sem2"): [
        "Linear Algebra for Economists", "Microeconomics II", "Macroeconomics II",
        "Statistics for Economists", "Fundamental of Accounting II",
        "Basic Writing Skill",
    ],
    ("Social Sciences & Humanities", "Economics", "Year3", "Sem1"): [
        "Mathematical Economics", "Econometrics I", "Development Economics I",
        "International Economics I", "Labour Economics",
        "Financial Economics", "Introduction to Management",
    ],
    ("Social Sciences & Humanities", "Economics", "Year3", "Sem2"): [
        "Econometrics II", "Research method for Economists",
        "Development Economics II", "International Economics II",
        "Economics of Industry", "Natural resource and Environmental Economics",
        "Practical Attachment",
    ],
    ("Social Sciences & Humanities", "Economics", "Year4", "Sem1"): [
        "Agricultural Economics", "Monetary Economics",
        "Project planning and Analysis I", "History of Economic thought I",
        "Introduction to Institutional and Behavioral Economics",
        "Statistical software Application in Economics", "Thesis in Economics I",
    ],
    ("Social Sciences & Humanities", "Economics", "Year4", "Sem2"): [
        "Rural development", "Public Finance", "Project planning and Analysis II",
        "History of Economic thought II", "Urban and regional Economics",
        "Thesis in Economics II",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "Management", "Year2", "Sem1"): [
        "Computer Applications in Management", "Basic Writing Skills",
        "Microeconomics", "Introduction to Management",
        "Organization Theory", "Administrative & Business Communication",
        "Statistics for Management I",
    ],
    ("Social Sciences & Humanities", "Management", "Year2", "Sem2"): [
        "Mathematics for Management", "Principle of Marketing",
        "Fundamentals of Accounting I", "Statistics for Management II",
        "Macroeconomics", "Organizational Behavior",
    ],
    ("Social Sciences & Humanities", "Management", "Year3", "Sem1"): [
        "Materials Management", "Human Resource Management",
        "International Marketing", "Fundamentals of Accounting II",
        "Management Information System", "Econometrics for Management",
    ],
    ("Social Sciences & Humanities", "Management", "Year3", "Sem2"): [
        "Leadership & Change Management", "Business Research Method",
        "Cost Management & Accounting I", "System Analysis and Design",
        "Business Law", "Managerial Economics",
    ],
    ("Social Sciences & Humanities", "Management", "Year4", "Sem1"): [
        "Internship in Management",
        "Business Ethics & Corporate Social Responsibility",
        "Cost and Management Accounting II", "Operations Research",
        "Financial Management", "Risk Management and Insurance",
        "Research in Management I",
    ],
    ("Social Sciences & Humanities", "Management", "Year4", "Sem2"): [
        "Operations Management", "Management of Financial Institutions",
        "Innovation Management and Entrepreneurship", "Project Management",
        "Strategic Management", "Research in Management II",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — MARKETING MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "Marketing Management", "Year2", "Sem1"): [
        "Introduction to Management", "Principles of Marketing",
        "Microeconomics", "Consumer Behavior", "Business Law",
        "Introduction to ICT",
    ],
    ("Social Sciences & Humanities", "Marketing Management", "Year2", "Sem2"): [
        "Business Communication", "Sales Management", "Retails Management",
        "Organizational Behavior", "Risk Management & Insurance",
        "Integrated Marketing Communication",
    ],
    ("Social Sciences & Humanities", "Marketing Management", "Year3", "Sem1"): [
        "Business Mathematics", "Fundamentals of Accounting I",
        "Managerial Statistics", "Services Marketing",
        "Social Marketing", "E-Marketing",
    ],
    ("Social Sciences & Humanities", "Marketing Management", "Year3", "Sem2"): [
        "Project Management", "Fundamentals of Accounting II",
        "Marketing Information system", "Event Management",
        "Tourism & Hospitality Marketing", "Marketing Research",
    ],
    ("Social Sciences & Humanities", "Marketing Management", "Year4", "Sem1"): [
        "Marketing Channel & Logistics Management",
        "Product & Brand Management", "Financial Management",
        "Business Marketing", "Apprenticeship in Marketing",
        "International Marketing",
    ],
    ("Social Sciences & Humanities", "Marketing Management", "Year4", "Sem2"): [
        "Agricultural and Commodity Marketing",
        "Import/Export Policy & Procedure",
        "Strategic Marketing Management", "Operations Management",
        "Negotiation Management", "Senior Essay in Marketing",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — AMHARIC & ETHIOPIAN LANGUAGE
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "Amharic & Ethiopian Language", "Year2", "Sem1"): [
        "Amharic Reading skills", "Amharic Oral Communicative Skills",
        "Amharic Basic Writing", "Fundamentals of Literature",
        "Introduction to Language and Linguistics",
        "Introduction to Media and Information Literacy",
    ],
    ("Social Sciences & Humanities", "Amharic & Ethiopian Language", "Year2", "Sem2"): [
        "Introduction to folklore", "Amharic advanced composition",
        "General Linguistics", "Issues in Multilingual and Multicultural Society",
        "Basic Geez", "Literary Readings and Human Concerns",
    ],
    ("Social Sciences & Humanities", "Amharic & Ethiopian Language", "Year3", "Sem1"): [
        "Technical Writing", "Amharic Novel", "Amharic Phonology and Morphology",
        "Introduction to Drama", "Amharic Oral Literature", "Language and Society",
    ],
    ("Social Sciences & Humanities", "Amharic & Ethiopian Language", "Year3", "Sem2"): [
        "Introduction Public Relations", "Amharic syntax", "Amharic Poetry",
        "Amharic Short Story", "Research Methods", "Internship",
    ],
    ("Social Sciences & Humanities", "Amharic & Ethiopian Language", "Year4", "Sem1"): [
        "Seminar on pre-research activities", "Practical Literary Criticism",
        "Translation Theory and Practice I",
        "Amharic Critical Reading and Text Analysis",
        "Children Literature", "News Gathering, Editorial and Feature writing",
    ],
    ("Social Sciences & Humanities", "Amharic & Ethiopian Language", "Year4", "Sem2"): [
        "Translation Theory and Practice II", "Workshop on creative writing",
        "Survey of Ethiopian Literature", "Workshop in Text Editing",
        "Survey of Ethiopian Languages", "Senior essay",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — CIVICS & ETHICAL STUDIES
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "Civics & Ethical Studies", "Year2", "Sem1"): [
        "Society, State & government", "Citizenship: Theory & Practices",
        "Political Philosophy I", "Social Change and Social Institutions",
        "Introduction to Philosophy", "Applied Ethics",
    ],
    ("Social Sciences & Humanities", "Civics & Ethical Studies", "Year2", "Sem2"): [
        "Survey of Human Rights", "Political Philosophy II",
        "Democracy and Election", "Constitution and Constitutionalism",
        "Introduction to Peace & Conflict", "Moral Philosophy",
    ],
    ("Social Sciences & Humanities", "Civics & Ethical Studies", "Year3", "Sem1"): [
        "Politics of the Horn and Middle East",
        "Survey of African Socio-Political Systems",
        "Development Theory & Practice", "Federalism: Theory and Practice",
        "Diversity and Multiculturalism", "Qualitative Research Method I",
    ],
    ("Social Sciences & Humanities", "Civics & Ethical Studies", "Year3", "Sem2"): [
        "Issues on Gender and Corruption", "Migration and Human Security",
        "Public Policy Formulation & Administration in Ethiopia",
        "Indigenous Conflict Resolution Mechanisms and Peace Building",
        "International Political Economy", "Qualitative Research Method II",
    ],
    ("Social Sciences & Humanities", "Civics & Ethical Studies", "Year4", "Sem1"): [
        "Regional Cooperation & Integration",
        "Ethiopian Foreign Policy & Diplomacy",
        "International Law and International Organizations",
        "Project Planning & Development", "Senior Essay I",
    ],
    ("Social Sciences & Humanities", "Civics & Ethical Studies", "Year4", "Sem2"): [
        "Professional Ethics & Civic Virtue",
        "Public Law and Public Administration",
        "Politics of Development Dynamism in Ethiopia",
        "Environmental Governance & Sustainable Development",
        "Contemporary Global Issues", "Senior Essay II",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — ENGLISH LANGUAGE & LITERATURE
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "English Language & Literature", "Year2", "Sem1"): [
        "Grammar in use", "Spoken English I", "Listening skills",
        "language and linguistics", "Fundamentals of literature", "Reading skills I",
    ],
    ("Social Sciences & Humanities", "English Language & Literature", "Year2", "Sem2"): [
        "Sophomore English", "Spoken English II", "Reading skills II",
        "Phonetics and phonology", "Theory of communication",
        "Selected world literature in English",
    ],
    ("Social Sciences & Humanities", "English Language & Literature", "Year3", "Sem1"): [
        "Advanced Writing I", "Morphology & syntax", "Short Story",
        "Advanced Speech", "Principles and Practices in Journalism",
        "Research and Report Writing",
    ],
    ("Social Sciences & Humanities", "English Language & Literature", "Year3", "Sem2"): [
        "The Novel", "Advanced writing II", "Introduction to Poetry",
        "Semantics and Pragmatics", "Ethiopian Literature in English",
        "Introduction Literary theory and criticism",
    ],
    ("Social Sciences & Humanities", "English Language & Literature", "Year4", "Sem1"): [
        "African Literature in English", "poetry",
        "English in Public relation", "Socio Linguistics",
        "Seminar on a Selected Topics", "Editing",
    ],
    ("Social Sciences & Humanities", "English Language & Literature", "Year4", "Sem2"): [
        "Translation and interpretation", "Creative writing",
        "Media English", "Discourse analysis", "Senior essay",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — GEOGRAPHY & ENVIRONMENTAL STUDIES
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "Geography & Environmental Studies", "Year2", "Sem1"): [
        "Introduction to Geographic Thought",
        "Introduction to Computer Applications",
        "Introduction to Climate", "Geomorphology", "Economic Geography",
    ],
    ("Social Sciences & Humanities", "Geography & Environmental Studies", "Year2", "Sem2"): [
        "Quantitative Techniques & Spatial Analysis",
        "Cartography and Map Reading", "Applied Climatology",
        "Environmental Hydrology", "Agroecology and Farming System",
        "Cultural and Social Geography",
    ],
    ("Social Sciences & Humanities", "Geography & Environmental Studies", "Year3", "Sem1"): [
        "Development Geography", "Geography of Population and Settlement",
        "Introduction to Surveying", "Introduction to GIS",
        "Geography of Natural Resources Analysis & Management", "Soil Geography",
    ],
    ("Social Sciences & Humanities", "Geography & Environmental Studies", "Year3", "Sem2"): [
        "Terrain Analysis and Land Use Planning", "Applied GIS",
        "Fundamentals of Remote Sensing",
        "Geography of Transport and Development",
        "Urban Geography", "Research Methods",
    ],
    ("Social Sciences & Humanities", "Geography & Environmental Studies", "Year4", "Sem1"): [
        "Urban and Regional Planning", "Geography of Tourism and Development",
        "Land Administration and Registration",
        "Environmental Policy, Ethics and Governance",
        "Biogeography", "Project Design and Management",
    ],
    ("Social Sciences & Humanities", "Geography & Environmental Studies", "Year4", "Sem2"): [
        "Seminar on Contemporary Geographical Issues", "Political Geography",
        "Livelihood and Food Security",
        "Environmental Hazard and Risk Management",
        "Environmental Impact Assessment", "Senior Essay",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — GOVERNANCE & DEVELOPMENT STUDIES
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "Governance & Development Studies", "Year2", "Sem1"): [
        "Political Thought I", "Introduction to Research Methods",
        "Introduction to Management", "Development Theories and Practices",
        "Introduction to Politics and Government",
        "Theories and Practice of Governance", "Introduction to Multiculturalism",
    ],
    ("Social Sciences & Humanities", "Governance & Development Studies", "Year2", "Sem2"): [
        "Political Thought II", "Organizational Leadership and Management",
        "International Relations and Organizations", "Development Economics",
        "Comparative Government and Political Systems",
        "Urban Governance and Municipal management",
        "Introduction to Public Administration",
    ],
    ("Social Sciences & Humanities", "Governance & Development Studies", "Year3", "Sem1"): [
        "Gender and Development", "Governance and Institutional Reform",
        "African Politics and International Relations",
        "International Political Economy", "Population and Development",
        "Constitutional Law and Constitutionalism",
        "Land Governance in Ethiopia",
    ],
    ("Social Sciences & Humanities", "Governance & Development Studies", "Year3", "Sem2"): [
        "Development Finance", "Human Resource Management",
        "Federalism and Local Government in Ethiopia",
        "Public Policy Making and Analyses", "Public International Law",
        "Development Planning and management", "Administrative Law",
    ],
    ("Social Sciences & Humanities", "Governance & Development Studies", "Year4", "Sem1"): [
        "Human Rights and Humanitarian Assistance",
        "Conflict Management and Peace Building",
        "Research methods in Social Sciences",
        "Community Development",
        "Political Systems and Governance in Ethiopia",
        "Project Planning and Management",
    ],
    ("Social Sciences & Humanities", "Governance & Development Studies", "Year4", "Sem2"): [
        "Seminar on Development Policies and Practices in Ethiopia",
        "Regional Growth and Local Development", "Rural Development",
        "Environment and Natural Resource Management",
        "Foreign policy and Diplomacy", "Senior essay",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — HISTORY & HERITAGE MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "History & Heritage Management", "Year2", "Sem1"): [
        "Philosophy of History and Historiography",
        "Ethiopia and the Horn to 1270", "Africa to 1500",
        "Ancient and Medieval World to 1500", "Introduction to Archaeology",
    ],
    ("Social Sciences & Humanities", "History & Heritage Management", "Year2", "Sem2"): [
        "Ethiopia and the Horn, 1270-1527", "Africa, 1500-1884",
        "The Early Modern World to 1789",
        "Archaeology of Ethiopia and the Horn",
        "Historical Research Methods I", "Introduction to Museology",
    ],
    ("Social Sciences & Humanities", "History & Heritage Management", "Year3", "Sem1"): [
        "Ethiopia and the Horn, 1527-1896",
        "History of Hydropolitics in the Nile Basin to 1959",
        "Africa, 1884-1960", "World History, 1789-1848",
        "Cultural Heritage Management", "Survey of the Islamic World to 1918",
    ],
    ("Social Sciences & Humanities", "History & Heritage Management", "Year3", "Sem2"): [
        "Ethiopia and the Horn, 1896-1941", "Africa 1960 to the Present",
        "The Modern World, 1848-1945", "The Middle East Since 1918",
        "Introduction to Ethiopian Arts and Architecture",
        "Historical Research Method II",
    ],
    ("Social Sciences & Humanities", "History & Heritage Management", "Year4", "Sem1"): [
        "Ethiopia and the Horn, 1941-1974",
        "History of Hydropolitics in the Nile Basin Since 1959",
        "History of Modern Latin America", "The Modern Pacific World",
        "Heritage Conservation and Management in Ethiopia",
    ],
    ("Social Sciences & Humanities", "History & Heritage Management", "Year4", "Sem2"): [
        "Ethiopia and the Horn, 1974-1995", "Global Developments Since 1945",
        "Tourism Resource and Tourism Management in Ethiopia", "Senior Essay",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — JOURNALISM & COMMUNICATION
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "Journalism & Communication", "Year2", "Sem1"): [
        "Introduction to Journalism", "Survey of Ethiopian Mass Media",
        "Introduction to Communication", "Development Journalism",
        "English for Journalists", "Introduction to Public Relations",
    ],
    ("Social Sciences & Humanities", "Journalism & Communication", "Year2", "Sem2"): [
        "Media and information literacy", "Media Translation",
        "Intercultural Communication", "Rural and Agricultural Communication",
        "News Writing and Reporting for Print",
        "Broadcast News Writing and Reporting",
    ],
    ("Social Sciences & Humanities", "Journalism & Communication", "Year3", "Sem1"): [
        "Communication Theories", "Public Relations: Theories and Practices",
        "Advertising and Social Marketing", "Photo Journalism",
        "Feature Writing", "Advanced Reporting", "Data Journalism",
    ],
    ("Social Sciences & Humanities", "Journalism & Communication", "Year3", "Sem2"): [
        "Media and Communication Research Methods",
        "Online Journalism and social media", "Investigative Journalism",
        "Media Law and Ethics", "Publication Layout and Design",
        "Broadcast news production",
    ],
    ("Social Sciences & Humanities", "Journalism & Communication", "Year4", "Sem1"): [
        "Newspaper Production", "Broadcast Program Production",
        "Health Communication", "Media Management", "Senior Essay I", "Internship",
    ],
    ("Social Sciences & Humanities", "Journalism & Communication", "Year4", "Sem2"): [
        "Senior Essay II", "Communication and Conflict Management",
        "Magazine Production", "Broadcast Documentary Production",
        "Business Communication", "International communication",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — EDUCATIONAL PLANNING & MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "Educational Planning & Management", "Year2", "Sem1"): [
        "Information and communication technology",
        "Introduction to Educational Management",
        "Educational Organization & Management I",
        "Educational Organization & Management II",
        "Educational Psychology",
        "Introduction to history and philosophy of education",
    ],
    ("Social Sciences & Humanities", "Educational Planning & Management", "Year2", "Sem2"): [
        "Basic Writing Skills", "Introduction to Educational Research",
        "Introduction to Statistical Methods in Education",
        "Action Research for Educational Managers",
        "School and the Community",
        "Multicultural Education and Diversity Management", "Internship I",
    ],
    ("Social Sciences & Humanities", "Educational Planning & Management", "Year3", "Sem1"): [
        "Introduction to educational leadership",
        "Management of Change and Innovation",
        "Group Dynamics and Conflict Management in Education",
        "Introduction to Guidance and Counseling",
        "Education and Development",
        "Management of Adult and Non-formal Education",
        "Management of Technical and Vocational Education and Training",
    ],
    ("Social Sciences & Humanities", "Educational Planning & Management", "Year3", "Sem2"): [
        "Economics of Education", "Macro Planning in Education",
        "Education Management Information System",
        "School Mapping and Micro Planning in Education",
        "Management of Educational project and Program Evaluation", "Internship II",
    ],
    ("Social Sciences & Humanities", "Educational Planning & Management", "Year4", "Sem1"): [
        "Education Policy Formulation, Implementation and Evaluation",
        "Decentralized Education Management", "Instructional Leadership",
        "Curriculum development", "Educational Supervision and inspection",
        "School Improvement and development",
        "Quality Management in Education", "Senior Essay A",
    ],
    ("Social Sciences & Humanities", "Educational Planning & Management", "Year4", "Sem2"): [
        "Human Resources Management in Education",
        "School leadership Development",
        "Finance and Property Management in Education",
        "Instructional Technology", "General Methods of Teaching",
        "Educational Measurement and Evaluation", "Senior Essay B",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — PSYCHOLOGY
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "Psychology", "Year2", "Sem1"): [
        "Physiological Psychology", "Psychology of Childhood",
        "Educational Measurement and Evaluation",
        "Educational Psychology", "Early Childhood care and Education",
    ],
    ("Social Sciences & Humanities", "Psychology", "Year2", "Sem2"): [
        "Psychological Testing", "Experimental Psychology",
        "Psychology of Adolescence", "Statistical Methods in Psychology I",
        "Cognitive Psychology", "Introduction to Guidance and Counseling",
    ],
    ("Social Sciences & Humanities", "Psychology", "Year3", "Sem1"): [
        "Psychology of Adulthood and Aging", "Research Methods in Psychology",
        "Introduction to Social Psychology",
        "Industrial/Organizational Psychology",
        "Theories and Techniques of Counseling",
        "Personality Psychology", "Practicum in Psychology I",
    ],
    ("Social Sciences & Humanities", "Psychology", "Year3", "Sem2"): [
        "Forensic Psychology", "Gender and Human Sexuality",
        "Crises and Trauma Counseling", "Cross Cultural Psychology",
        "Psychopathology", "Psychology of Addiction",
    ],
    ("Social Sciences & Humanities", "Psychology", "Year4", "Sem1"): [
        "Health Psychology", "Statistical Methods in Psychology II",
        "Community Psychology", "Psychopharmacology",
        "Clinical Psychology", "Sport Psychology",
    ],
    ("Social Sciences & Humanities", "Psychology", "Year4", "Sem2"): [
        "Marriage and Family Counseling", "Seminar in Contemporary Issues",
        "Project Design and Management", "Practicum in Psychology II",
        "Career Development and Counseling", "Senior Essay in Psychology",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — SOCIAL WORK
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "Social Work", "Year2", "Sem1"): [
        "Introduction to Social Work", "Methods of social Work Practice I",
        "Methods of social Work Practice II",
        "Introduction to Population Studies",
        "Contemporary Social Issues and Social Work",
        "Introduction to Sociology",
    ],
    ("Social Sciences & Humanities", "Social Work", "Year2", "Sem2"): [
        "Theories of Human Behavior and the Social Environment",
        "Health Social Work", "Criminal Justice Social Work",
        "Qualitative Research Methods", "Field Education I",
    ],
    ("Social Sciences & Humanities", "Social Work", "Year3", "Sem1"): [
        "Quantitative Research Methods", "Gender, Diversity and Social work",
        "Social Welfare Services", "Social Policy Practice",
        "Migration, Refugee and Social Work Practice",
        "Statistics for Social Workers",
    ],
    ("Social Sciences & Humanities", "Social Work", "Year3", "Sem2"): [
        "Hospital Social Work", "Psychiatric Social Work",
        "Organizational Management and Leadership",
        "Project Design and Management", "Law for Social Workers",
        "Field education II",
    ],
    ("Social Sciences & Humanities", "Social Work", "Year4", "Sem1"): [
        "Case Management", "Counselling in Social Work",
        "Correctional Rehabilitation and Administration",
        "Working with Children and Families", "School Social Work",
        "Social Development and Community Practice",
    ],
    ("Social Sciences & Humanities", "Social Work", "Year4", "Sem2"): [
        "Rehabilitation Services and Disability", "Gerontology",
        "Field Education III", "Senior Paper",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL SCIENCES — SOCIOLOGY
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Sciences & Humanities", "Sociology", "Year2", "Sem1"): [
        "Introduction to Sociology", "Sociology of Peace and Conflict",
        "Social Institutions I", "Social Institution II",
        "Sociology of Ethiopian Societies",
    ],
    ("Social Sciences & Humanities", "Sociology", "Year2", "Sem2"): [
        "Sociological Theories I", "Media, Communication and culture",
        "Sociology of Social Change", "Sociology of Population",
        "Sociology of Modernization and Development",
    ],
    ("Social Sciences & Humanities", "Sociology", "Year3", "Sem1"): [
        "Sociological Theories II", "Sociology of Tourism",
        "Statistics for Sociologists I", "Social Research Methods I",
        "Population Movement, Migration, Resettlement", "Economic Sociology",
    ],
    ("Social Sciences & Humanities", "Sociology", "Year3", "Sem2"): [
        "Medical Sociology", "Sociology of work, Industry and Organization",
        "Statistics For Sociologist II", "Social Research Methods II",
        "Rural Sociology and Rural Development", "Urban Sociology",
    ],
    ("Social Sciences & Humanities", "Sociology", "Year4", "Sem1"): [
        "Sociology of Deviance", "Social policy and planning",
        "Globalization, Social Movement and Civil Society",
        "Environmental Sociology",
        "Social Problem and Methods of Intervention I", "Senior Essay",
    ],
    ("Social Sciences & Humanities", "Sociology", "Year4", "Sem2"): [
        "Criminology and Correctional Administration",
        "Project Design and Management", "Social Identities",
        "Social problems and Methods of intervention II",
        "Sociology of Gender", "Senior Essay",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # LAW — Year 1 Common (Social Sciences stream + Basic Law Course)
    # ══════════════════════════════════════════════════════════════════════════
    ("Law", "", "Year1", "Sem1"): [
        "Communicative English Skills I", "Economics", "General Psychology",
        "Mathematics for Social Sciences", "Critical Thinking", "Physical fitness",
        "Geography of Ethiopia & the Horn",
    ],
    ("Law", "", "Year1", "Sem2"): [
        "Communicative English Skills II", "Social Anthropology",
        "Entrepreneurship", "History of Ethiopia & the Horn",
        "Introduction to emerging Technologies", "Basic Law Course",
        "Global Trends",
    ],

    # ══════════════════════════════════════════════════════════════════════════
    # LAW (5 years)
    # ══════════════════════════════════════════════════════════════════════════
    ("Law", "Law", "Year2", "Sem1"): [
        "Law of Persons", "Legal History and Customary Law",
        "Jurisprudence", "Law of Contracts I", "Constitutional Law",
    ],
    ("Law", "Law", "Year2", "Sem2"): [
        "Family Law", "Succession law", "Contracts Law II",
        "Criminal Law I", "Property Law", "Legal Research Methodology",
    ],
    ("Law", "Law", "Year3", "Sem1"): [
        "Land Law", "Law of Extra-Contractual Liability",
        "Law of Special Contracts", "Criminal Law II",
        "Civil Procedure I", "Law of Traders and Business Organization",
    ],
    ("Law", "Law", "Year3", "Sem2"): [
        "Civil Procedure II", "Criminal Procedure", "Law of Evidence",
        "Public International Law",
        "Law of Banking, Insurance and Negotiable Instruments", "Federalism",
    ],
    ("Law", "Law", "Year4", "Sem1"): [
        "Law of Insurance", "Law of Banking and Negotiable Instruments",
        "Public International Law", "International Humanitarian Law",
        "Environmental Law", "Water Law", "Construction Law",
    ],
    ("Law", "Law", "Year4", "Sem2"): [
        "International Trade Law", "Investment Law", "Human Rights Law",
        "African Union and Human Rights Law", "Gender and Law",
        "Employment Laws", "Sentencing and Execution",
    ],
    ("Law", "Law", "Year5", "Sem1"): [
        "Pre-Trial, Trial and Appellate Advocacy / Moot Court",
        "Legal Clinics", "Legal Ethics",
        "Alternative Dispute Resolution", "Senior Thesis",
    ],
    ("Law", "Law", "Year5", "Sem2"): [
        "Exit Exam", "Externship",
    ],
}

# ── Year / Semester display helpers ──────────────────────────────────────────

YEARS        = ["📗 Year 1", "📘 Year 2", "📙 Year 3", "📕 Year 4", "📓 Year 5"]
YEAR_LABELS  = ["Year1", "Year2", "Year3", "Year4", "Year5"]
SEMESTERS    = [("📙 Semester 1", "Sem1"), ("📗 Semester 2", "Sem2")]

ALLOWED_EXTENSIONS = {".pdf", ".ppt", ".pptx", ".doc", ".docx"}
MAX_FILE_SIZE      = 20 * 1024 * 1024  # 20 MB

MEDALS    = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
STARS_MAP = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐", 4: "⭐⭐⭐⭐", 5: "⭐⭐⭐⭐⭐"}
DIVIDER   = "━" * 20

IDENTITY_KEYWORDS = [
    "who made you", "who are you", "who created you", "who built you",
    "who developed you", "your creator", "your developer", "your maker",
    "are you gemini", "are you chatgpt", "are you openai", "are you google",
    "what are you", "tell me about yourself", "introduce yourself",
    "who is your creator", "your origin", "who owns you",
    "ማን ሰራህ", "ማን ነህ", "ማን ፈጠርህ",
]

IDENTITY_RESPONSE_EN = (
    "🤖 *I am mtu.ai*\n"
    f"{DIVIDER}\n"
    "I was developed by *Andarge Girma*.\n\n"
    "If you wish to reach my creator, tap the\n"
    "💬 *Contact* button to speak with them directly."
)

IDENTITY_RESPONSE_AM = (
    "🤖 *እኔ mtu.ai ነኝ*\n"
    f"{DIVIDER}\n"
    "እኔ የተሰራሁት በ *አንዳርጌ ጊርማ* ነው።\n\n"
    "ፈጣሪዬን ለማግኘት\n"
    "💬 *ያግኙ* ቁልፍን ይጫኑ።"
)

MTU_WELCOME_EN = (
    "🤖 *mtu.ai — Your Smart Study Assistant*\n"
    f"{DIVIDER}\n"
    "Ask me anything academic!\n\n"
    "📚 Study tips\n"
    "🔬 Science questions\n"
    "📐 Math problems\n"
    "💡 Explanations\n\n"
    "_Type your question below 👇_"
)

MTU_WELCOME_AM = (
    "🤖 *mtu.ai — ብልህ የጥናት ረዳትዎ*\n"
    f"{DIVIDER}\n"
    "ማንኛውንም የትምህርት ጥያቄ ይጠይቁ!\n\n"
    "📚 የጥናት ምክሮች\n"
    "🔬 የሳይንስ ጥያቄዎች\n"
    "📐 የሒሳብ ችግሮች\n"
    "💡 ማብራሪያዎች\n\n"
    "_ጥያቄዎን ከዚህ ይጻፉ 👇_"
)

MTU_AI_COMING_SOON_EN = (
    "🤖 *mtu.ai — Coming Soon!*\n"
    f"{DIVIDER}\n"
    "The AI feature is currently under maintenance.\n"
    "Please check back later. 🙏"
)

MTU_AI_COMING_SOON_AM = (
    "🤖 *mtu.ai — በቅርቡ ይመጣል!*\n"
    f"{DIVIDER}\n"
    "AI ባህሪው በጥገና ላይ ነው።\n"
    "ቆይቶ ይሞክሩ። 🙏"
)

AI_SYSTEM_PROMPT = (
    "You are mtu.ai, an intelligent academic assistant for Mizan-Tepi University (MTU) "
    "students in Ethiopia. Help students with their academic questions, study tips, "
    "explanations of concepts, math problems, science questions, and anything related "
    "to their university studies. Be concise, clear, and helpful. "
    "If asked about your identity, say you are mtu.ai developed by Andarge Girma. "
    "Respond in the same language the user uses (English or Amharic)."
)

# ── Texts dict ────────────────────────────────────────────────────────────────

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "welcome": (
            "🎓 *MTU File Sharing Bot*\n"
            f"{DIVIDER}\n"
            "📚 Share · Find · Learn\n"
            "🤝 By Students, For Students\n"
            f"{DIVIDER}\n"
            "🌍 *Choose your language:*"
        ),
        "onboarding_faculty": (
            "🏫 *Tell us about your department!*\n"
            f"{DIVIDER}\n"
            "This helps us notify you when new files are uploaded to your department.\n\n"
            "📂 *Select your Faculty:*"
        ),
        "onboarding_dept": "📂 *Select your Department:*",
        "onboarding_year": "📅 *Select your current Year:*",
        "onboarding_done_en": (
            "✅ *Profile saved!*\n"
            "You'll get notified when new files are added to your department & year. 🔔"
        ),
        "onboarding_done_am": (
            "✅ *መረጃዎ ተቀምጧል!*\n"
            "ለዲፓርትመንትዎ አዲስ ፋይሎች ሲጨመሩ ማሳወቂያ ይደርስዎታል። 🔔"
        ),
        "skip_onboarding": "⏭️ Skip (Set up later)",
        "main_menu":              "🏠 *Main Menu* — choose below 👇",
        "browse":                 "📥 Download Center",
        "upload":                 "📤 Upload",
        "leaderboard":            "🏆 Leaderboard",
        "help":                   "❓ Help",
        "contact":                "💬 Contact",
        "mtu_ai":                 "🤖 mtu.ai",
        "search":                 "🔍 Search",
        "request_file":           "🆘 Request File",
        "select_faculty":         "🏫 *[1] Pick Category* 👇",
        "select_department":      "📂 *[2] Pick Department* 👇",
        "select_year":            "📅 *[3] Pick Year* 👇",
        "select_semester":        "📖 *Pick Semester* 👇",
        "select_course":          "📚 *Pick Course* 👇",
        "no_books": (
            "📭 *Empty Category*\n"
            f"{DIVIDER}\n"
            "No books here yet.\n"
            "💡 Be the first to upload! 🌟"
        ),
        "books_list":             "📚 *Books Available* — tap to download 👇",
        "download_success": (
            "✅ *File sent!* Good luck! 📖\n"
            f"{DIVIDER}\n"
            "⭐ *Rate this book:*"
        ),
        "already_voted":          "⚠️ You already rated this book.",
        "vote_recorded":          "🎉 *Rating saved!* Thanks! 💪",
        "upload_select_location": (
            "📤 *Upload*\n"
            f"{DIVIDER}\n"
            "Select where to place the book:\n"
            "Category → Dept → Year → Semester → Course\n\n"
            "Or choose *Unordered Upload* to skip course selection."
        ),
        "upload_prompt": (
            "📎 *Send your file now!*\n"
            f"{DIVIDER}\n"
            "✅ `PDF · PPT · PPTX · DOC · DOCX`\n"
            "📏 Max: `20 MB`"
        ),
        "upload_success": (
            "🎊 *Uploaded!* Thank you! 🌟\n"
            "You earned +1 upload badge 📛"
        ),
        "upload_duplicate":       "⚠️ *Duplicate* — this file already exists here.",
        "upload_invalid_type":    "❌ *Wrong file type*\nUse: `PDF · PPT · PPTX · DOC · DOCX`",
        "upload_too_large":       "❌ *Too large* — max is *20 MB*.",
        "upload_error":           "❌ Upload failed. Please try again.",
        "leaderboard_title":      "🏆 *Top Contributors* 💪\n" + f"{DIVIDER}\n\n",
        "leaderboard_empty": (
            "🏆 *Leaderboard*\n"
            f"{DIVIDER}\n"
            "No one yet!\n"
            "📤 Upload and claim 🥇!"
        ),
        "help_text": (
            "❓ *Help*\n"
            f"{DIVIDER}\n"
            "📥 *Download Center*\n"
            "   Browse by Category › Dept › Year › Semester › Course\n"
            "   Or tap *General/Unordered Files* to see uncategorised files\n\n"
            "📤 *Upload*\n"
            "   Share PDF/PPT/DOC (max 20 MB)\n"
            "   Supports *Ordered Upload* (Faculty→Dept→Year→Semester→Course)\n"
            "   or *Unordered Upload* (skip course selection)\n\n"
            "➕ *Create Custom Course*\n"
            "   After selecting semester, create your own course!\n"
            "   Everyone can upload and download from that course.\n\n"
            "🆘 *Request File*\n"
            "   Can't find what you need? Post in our group!\n\n"
            "🔍 *Search* → find any file by name or keyword\n"
            "⭐ *Rate* → after downloading\n"
            "🤖 *mtu.ai* → AI study assistant\n"
            "🏆 *Leaderboard* → top uploaders\n"
            "💬 *Contact* → message the owner\n"
            f"{DIVIDER}\n"
            "💡 More uploads = higher rank! 🚀"
        ),
        "contact_prompt": (
            "💬 *Contact Owner*\n"
            f"{DIVIDER}\n"
            "Type your message 👇\n"
            "_(Your name & ID are auto-included)_"
        ),
        "contact_sent":           "✅ *Sent!* The owner will reply soon 😊",
        "contact_error":          "❌ Failed to send. Please try again.",
        "back":                   "⬅️ Back",
        "main_menu_btn":          "🏠 Menu",
        "exit_chat":              "🚪 Exit Chat",
        "rate_1": "1⭐", "rate_2": "2⭐", "rate_3": "3⭐",
        "rate_4": "4⭐", "rate_5": "5⭐",
        "books": "📚", "stars": "⭐",
        "search_prompt": (
            "🔍 *Search*\n"
            f"{DIVIDER}\n"
            "Type a book name or keyword 👇"
        ),
        "search_results":         "🔍 *Results* — tap to download 👇",
        "search_no_results":      "🔍 *Nothing found*\nTry a shorter keyword or browse 📚",
        "not_admin":              "⛔ Not authorized.",
        "spam_warning":           "⏳ Please wait before uploading again.",
        "uploading":              "⏳ *Saving...* please wait!",
        "file_not_found":         "❌ File not found or has been removed.",
        "ai_thinking":            "🤖 *mtu.ai is thinking...*",
        "ai_error":               "⚠️ AI is unavailable right now. Please try again later.",
        "ai_no_key":              "⚠️ AI feature is not configured yet.",
        "general_files":          "📚 General / Unordered Files",
        "help_bot_prompt": (
            "🆘 *Help the Bot!*\n"
            f"{DIVIDER}\n"
            "This file is unordered. Which course does it belong to?\n"
            "Tap a course below to tag it, or skip."
        ),
        "help_bot_tagged":        "✅ *Tagged!* Thank you for helping! 🌟",
        "help_bot_skip":          "⏭️ Skip",
        "unordered_upload":       "📦 Unordered Upload",
        "unordered_upload_prompt": (
            "📦 *Unordered Upload*\n"
            f"{DIVIDER}\n"
            "Send your file. It will be saved without a specific course.\n"
            "You (or others) can tag it to a course later.\n\n"
            "📎 *Send your file now!*\n"
            "✅ `PDF · PPT · PPTX · DOC · DOCX`\n"
            "📏 Max: `20 MB`"
        ),
        "create_course":          "➕ Create Custom Course",
        "create_course_prompt": (
            "✏️ *Create Custom Course*\n"
            f"{DIVIDER}\n"
            "Type the course name you want to create 👇\n"
            "_(e.g. Calculus I, Linear Algebra, etc.)_"
        ),
        "course_created":         "✅ *Course created!* You can now upload files to it.",
        "course_exists":          "⚠️ This course already exists here.",
        "course_select_upload_prompt": "📚 *Select a course to upload to:*",
        "upload_to_course":       "📤 Upload to this course",
    },
    "am": {
        "welcome": (
            "🎓 *ዩኒ መጽሐፍ መካፈያ ቦት*\n"
            f"{DIVIDER}\n"
            "📚 ያጋሩ · ያግኙ · ይማሩ\n"
            "🤝 በተማሪዎች ለተማሪዎች\n"
            f"{DIVIDER}\n"
            "🌍 *ቋንቋ ይምረጡ:*"
        ),
        "onboarding_faculty": (
            "🏫 *ስለ ዲፓርትመንትዎ ይንገሩን!*\n"
            f"{DIVIDER}\n"
            "ለዲፓርትመንትዎ አዲስ ፋይሎች ሲጨመሩ ለማሳወቅ ይረዳናል።\n\n"
            "📂 *ፋካልቲዎን ይምረጡ:*"
        ),
        "onboarding_dept": "📂 *ዲፓርትመንትዎን ይምረጡ:*",
        "onboarding_year": "📅 *የአሁን ዓመትዎን ይምረጡ:*",
        "onboarding_done_en": (
            "✅ *Profile saved!*\n"
            "You'll get notified when new files are added to your department & year. 🔔"
        ),
        "onboarding_done_am": (
            "✅ *መረጃዎ ተቀምጧል!*\n"
            "ለዲፓርትመንትዎ አዲስ ፋይሎች ሲጨመሩ ማሳወቂያ ይደርስዎታል። 🔔"
        ),
        "skip_onboarding": "⏭️ ዝለል (ኋላ ማዋቀር)",
        "main_menu":              "🏠 *ዋና ምናሌ* — ይምረጡ 👇",
        "browse":                 "📥 ማውረጃ ማዕከል",
        "upload":                 "📤 ያስቀምጡ",
        "leaderboard":            "🏆 ሰንጠረዥ",
        "help":                   "❓ እርዳታ",
        "contact":                "💬 ያግኙ",
        "mtu_ai":                 "🤖 mtu.ai",
        "search":                 "🔍 ፍለጋ",
        "request_file":           "🆘 ፋይል ጠይቅ",
        "select_faculty":         "🏫 *[1] ምድብ ይምረጡ* 👇",
        "select_department":      "📂 *[2] ዲፓርትመንት ይምረጡ* 👇",
        "select_year":            "📅 *[3] ዓመት ይምረጡ* 👇",
        "select_semester":        "📖 *ሴሚስተር ይምረጡ* 👇",
        "select_course":          "📚 *ኮርስ ይምረጡ* 👇",
        "no_books": (
            "📭 *ምንም የለም*\n"
            f"{DIVIDER}\n"
            "ይህ ምድብ ባዶ ነው።\n"
            "💡 ቀዳሚ ሁኑ! 🌟"
        ),
        "books_list":             "📚 *መጽሐፍት* — ለማውረድ ይጫኑ 👇",
        "download_success": (
            "✅ *ፋይሉ ደረሰ!* ጥናትዎ ይሳካ! 📖\n"
            f"{DIVIDER}\n"
            "⭐ *ምዘና ይስጡ:*"
        ),
        "already_voted":          "⚠️ ቀድሞ ምዘና ሰጥተዋል።",
        "vote_recorded":          "🎉 *ምዘናዎ ተቀበልን!* አመሰግናለሁ! 💪",
        "upload_select_location": (
            "📤 *ያስቀምጡ*\n"
            f"{DIVIDER}\n"
            "ቦታ ይምረጡ:\n"
            "ምድብ → ዲፓ → ዓመት → ሴሚስተር → ኮርስ\n\n"
            "ወይም *ያልተደራጀ ስቀላ* ይምረጡ።"
        ),
        "upload_prompt": (
            "📎 *ፋይሉን ይላኩ!*\n"
            f"{DIVIDER}\n"
            "✅ `PDF · PPT · PPTX · DOC · DOCX`\n"
            "📏 ከፍ: `20 MB`"
        ),
        "upload_success": (
            "🎊 *ተጭኗል!* አመሰግናለሁ! 🌟\n"
            "+1 ስኬት አግኝተዋል! 📛"
        ),
        "upload_duplicate":       "⚠️ *ተደጋጋሚ* — ፋይሉ ቀድሞ አለ።",
        "upload_invalid_type":    "❌ *ልክ ያልሆነ*\n`PDF · PPT · PPTX · DOC · DOCX` ብቻ",
        "upload_too_large":       "❌ *ትልቅ ነው* — ከፍ: *20 MB*",
        "upload_error":           "❌ አልተሳካም። ድጋሚ ሞክሩ።",
        "leaderboard_title":      "🏆 *ምርጥ አስተዋጽዖ አድራጊዎች* 💪\n" + f"{DIVIDER}\n\n",
        "leaderboard_empty": (
            "🏆 *ሰንጠረዥ*\n"
            f"{DIVIDER}\n"
            "ማንም እስካሁን የለም!\n"
            "📤 ያስቀምጡ እና 🥇 ያሸንፉ!"
        ),
        "help_text": (
            "❓ *እርዳታ*\n"
            f"{DIVIDER}\n"
            "📥 *ማውረጃ ማዕከል*\n"
            "   ምድብ › ዲፓ › ዓመት › ሴሚ › ኮርስ\n"
            "   *ያልተደራጁ ፋይሎች* ለማየት ቁልፍ ይጫኑ\n\n"
            "📤 *ያስቀምጡ*\n"
            "   PDF/PPT/DOC (20MB)\n"
            "   *ተደራጀ ስቀላ* ወይም *ያልተደራጀ ስቀላ*\n\n"
            "➕ *ኮርስ ፍጠሩ*\n"
            "   ሴሚስተር ከመረጡ በኋላ የራስዎን ኮርስ ማስፈጠር ይችላሉ!\n\n"
            "🆘 *ፋይል ጠይቅ* → ቡድናችን ይቀላቀሉ!\n\n"
            "🔍 *ፍለጋ* → ፋይል ይፈልጉ\n"
            "⭐ *ምዘና* → ካወረዱ በኋላ\n"
            "🤖 *mtu.ai* → ብልህ የጥናት ረዳት\n"
            "🏆 *ሰንጠረዥ* → ምርጥ አስተዋጽዖ\n"
            "💬 *ያግኙ* → ለባለቤቱ\n"
            f"{DIVIDER}\n"
            "💡 ብዙ ያስቀምጡ = ሰፊ ደረጃ! 🚀"
        ),
        "contact_prompt": (
            "💬 *ባለቤቱን ያግኙ*\n"
            f"{DIVIDER}\n"
            "መልዕክትዎን ይጻፉ 👇\n"
            "_(ስምዎ ራስ-ሰር ይካተታል)_"
        ),
        "contact_sent":           "✅ *ተልኳል!* ብዙ ሳይቆይ ይደርስዎታል 😊",
        "contact_error":          "❌ አልተሳካም። ድጋሚ ሞክሩ።",
        "back":                   "⬅️ ተመለስ",
        "main_menu_btn":          "🏠 ምናሌ",
        "exit_chat":              "🚪 ውይይት አቁም",
        "rate_1": "1⭐", "rate_2": "2⭐", "rate_3": "3⭐",
        "rate_4": "4⭐", "rate_5": "5⭐",
        "books": "📚", "stars": "⭐",
        "search_prompt": (
            "🔍 *ፍለጋ*\n"
            f"{DIVIDER}\n"
            "የመጽሐፍ ስም ወይም ቃል ይጻፉ 👇"
        ),
        "search_results":         "🔍 *ውጤቶች* — ለማውረድ ይጫኑ 👇",
        "search_no_results":      "🔍 *ምንም አልተገኘም*\nአጭር ቃል ሞክሩ ወይም ፈልጉ 📚",
        "not_admin":              "⛔ ፈቃድ የለዎትም።",
        "spam_warning":           "⏳ ትንሽ ይጠብቁ።",
        "uploading":              "⏳ *እየተቀመጠ ነው...* ይጠብቁ!",
        "file_not_found":         "❌ ፋይሉ አልተገኘም።",
        "ai_thinking":            "🤖 *mtu.ai እያሰበ ነው...*",
        "ai_error":               "⚠️ AI አሁን አይሰራም። ቆይቶ ሞክሩ።",
        "ai_no_key":              "⚠️ AI ባህሪ አልተዋቀረም።",
        "general_files":          "📚 ያልተደራጁ ፋይሎች",
        "help_bot_prompt": (
            "🆘 *ቦቱን ይርዱ!*\n"
            f"{DIVIDER}\n"
            "ይህ ፋይል ያልተደራጀ ነው። ለየትኛው ኮርስ ነው?\n"
            "ከዚህ ይምረጡ ወይም ዝለሉ።"
        ),
        "help_bot_tagged":        "✅ *ተለጥፏል!* ስለ ርዳታዎ አመሰግናለሁ! 🌟",
        "help_bot_skip":          "⏭️ ዝለል",
        "unordered_upload":       "📦 ያልተደራጀ ስቀላ",
        "unordered_upload_prompt": (
            "📦 *ያልተደራጀ ስቀላ*\n"
            f"{DIVIDER}\n"
            "ፋይሉን ይላኩ። ያለ ኮርስ ይቀመጣል።\n"
            "ኋላ ሊደራጅ ይችላል።\n\n"
            "📎 *ፋይሉን ይላኩ!*\n"
            "✅ `PDF · PPT · PPTX · DOC · DOCX`\n"
            "📏 ከፍ: `20 MB`"
        ),
        "create_course":          "➕ ኮርስ ፍጠሩ",
        "create_course_prompt": (
            "✏️ *ኮርስ ስም ያስፈጥሩ*\n"
            f"{DIVIDER}\n"
            "ለመፍጠር የሚፈልጉትን ኮርስ ስም ይጻፉ 👇\n"
            "_(ምሳ: Calculus I, Linear Algebra, ወዘተ.)_"
        ),
        "course_created":         "✅ *ኮርስ ተፈጠረ!* አሁን ፋይሎችን ያስቀምጡ።",
        "course_exists":          "⚠️ ይህ ኮርስ ቀድሞ አለ።",
        "course_select_upload_prompt": "📚 *ፋይሉን ወደ ምን ኮርስ ያስቀምጡ:*",
        "upload_to_course":       "📤 ወደዚህ ኮርስ ያስቀምጡ",
    },
}

# ── In-memory database with channel-backed persistence ───────────────────────

_db_cache:     dict | None = None
_states_cache: dict | None = None
_db_lock     = threading.Lock()
_states_lock = threading.Lock()

_db_executor     = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="db_upload")
_states_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="st_upload")

_ai_enabled      = True
_ai_enabled_lock = threading.Lock()


def is_ai_enabled() -> bool:
    with _ai_enabled_lock:
        return _ai_enabled


def set_ai_enabled(val: bool) -> None:
    global _ai_enabled
    with _ai_enabled_lock:
        _ai_enabled = val


# ── Channel storage helpers ───────────────────────────────────────────────────

def _upload_to_channel(data: dict, filename: str) -> tuple[int, str]:
    if not DB_CHANNEL_ID:
        raise RuntimeError("DB_CHANNEL_ID is not set.")
    content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    buf = io.BytesIO(content)
    buf.name = filename
    msg = bot.send_document(DB_CHANNEL_ID, buf, caption=f"📦 {filename}")
    return msg.message_id, msg.document.file_id


def _download_from_channel(file_id: str) -> dict | None:
    try:
        file_info = bot.get_file(file_id)
        content   = bot.download_file(file_info.file_path)
        return json.loads(content.decode("utf-8"))
    except Exception as e:
        logger.error("Channel download failed (file_id=%s): %s", file_id, e)
        return None


def _save_index() -> None:
    payload = json.dumps({
        "db_msg":      DB_MSG_IDS.get("db_msg"),
        "db_file":     DB_MSG_IDS.get("db_file"),
        "states_msg":  DB_MSG_IDS.get("states_msg"),
        "states_file": DB_MSG_IDS.get("states_file"),
        "index_msg":   DB_MSG_IDS.get("index_msg"),
    })
    text = "MTU_BOT_INDEX:" + payload
    try:
        if DB_MSG_IDS.get("index_msg"):
            try:
                bot.edit_message_text(text, DB_CHANNEL_ID, DB_MSG_IDS["index_msg"])
                return
            except Exception:
                pass
        msg = bot.send_message(DB_CHANNEL_ID, text)
        DB_MSG_IDS["index_msg"] = msg.message_id
        try:
            bot.pin_chat_message(DB_CHANNEL_ID, msg.message_id, disable_notification=True)
        except Exception as pin_err:
            logger.warning("Could not pin index: %s", pin_err)
    except Exception as e:
        logger.error("Failed to save DB index: %s", e)


LOCAL_DB_PATH = os.environ.get("LOCAL_DB_PATH", "database.json")


def _load_local_db() -> dict | None:
    path = LOCAL_DB_PATH
    if not os.path.isfile(path):
        logger.info("No local %s found", path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("books"), list):
            logger.warning("Local %s has no valid 'books' list — skipping", path)
            return None
        logger.info("Local %s loaded ✅ (%d books, %d users)", path,
                    len(data.get("books", [])), len(data.get("users", {})))
        return data
    except Exception as e:
        logger.error("Failed to read local %s: %s", path, e)
        return None


def _merge_db(channel_data: dict | None, local_data: dict | None) -> dict:
    if channel_data is None and local_data is None:
        return {"books": [], "users": {}, "custom_courses": {}, "ai_enabled": True}
    if channel_data is None:
        return local_data
    if local_data is None:
        return channel_data

    existing_ids = {b.get("telegram_file_id") for b in channel_data.get("books", [])
                    if b.get("telegram_file_id")}
    new_books = [b for b in local_data.get("books", [])
                 if b.get("telegram_file_id") not in existing_ids]

    if new_books:
        logger.info("Merging %d new book(s) from local DB into channel DB", len(new_books))
        channel_data = dict(channel_data)
        channel_data["books"] = list(channel_data.get("books", [])) + new_books

    for key in ("users", "custom_courses"):
        if key in local_data and key not in channel_data:
            channel_data[key] = local_data[key]

    return channel_data


def _load_index() -> bool:
    global _db_cache, _states_cache, _ai_enabled
    try:
        chat = bot.get_chat(DB_CHANNEL_ID)
        if chat.pinned_message and chat.pinned_message.text:
            text = chat.pinned_message.text
            if text.startswith("MTU_BOT_INDEX:"):
                data = json.loads(text[len("MTU_BOT_INDEX:"):])
                DB_MSG_IDS.update({k: v for k, v in data.items() if v is not None})
                logger.info("DB index loaded ✅ db_msg=%s states_msg=%s",
                            DB_MSG_IDS.get("db_msg"), DB_MSG_IDS.get("states_msg"))

                channel_db = None
                if DB_MSG_IDS.get("db_file"):
                    channel_db = _download_from_channel(DB_MSG_IDS["db_file"])
                    if channel_db is not None and "ai_enabled" in channel_db:
                        with _ai_enabled_lock:
                            _ai_enabled = bool(channel_db["ai_enabled"])
                    if channel_db is not None:
                        logger.info("DB cache warmed ✅ (%d books)", len(channel_db.get("books", [])))

                local_db = _load_local_db()
                merged   = _merge_db(channel_db, local_db)
                _db_cache = merged

                channel_count = len(channel_db.get("books", [])) if channel_db else 0
                if len(merged.get("books", [])) > channel_count:
                    logger.info("Syncing merged DB back to channel (%d books)…",
                                len(merged.get("books", [])))
                    _db_executor.submit(_bg_save_db, merged)

                if DB_MSG_IDS.get("states_file"):
                    result = _download_from_channel(DB_MSG_IDS["states_file"])
                    if result is not None:
                        _states_cache = result
                        logger.info("States cache warmed ✅ (%d users)", len(result))
                return True

        logger.info("No pinned DB index — scanning updates for seed database…")
        try:
            updates = bot.get_updates(limit=100, allowed_updates=["message", "channel_post"])
        except Exception:
            updates = []

        channel_db = None
        for update in reversed(updates):
            msg = getattr(update, "message", None) or getattr(update, "channel_post", None)
            if not msg:
                continue
            if getattr(msg, "chat", None) and getattr(msg.chat, "id", None) == DB_CHANNEL_ID:
                doc   = getattr(msg, "document", None)
                fname = (getattr(doc, "file_name", "") or "") if doc else ""
                if fname == "database.json" and channel_db is None:
                    result = _download_from_channel(doc.file_id)
                    if result is not None and isinstance(result.get("books"), list):
                        channel_db = result
                        DB_MSG_IDS["db_msg"]  = msg.message_id
                        DB_MSG_IDS["db_file"] = doc.file_id
                        if "ai_enabled" in result:
                            with _ai_enabled_lock:
                                _ai_enabled = bool(result["ai_enabled"])
                        logger.info("Seed database.json loaded from channel ✅ (%d books)",
                                    len(result.get("books", [])))
                elif fname == "user_choices.json" and _states_cache is None:
                    result = _download_from_channel(doc.file_id)
                    if result is not None and isinstance(result, dict):
                        _states_cache = result
                        DB_MSG_IDS["states_msg"]  = msg.message_id
                        DB_MSG_IDS["states_file"] = doc.file_id
                        logger.info("Seed user_choices.json loaded from channel ✅ (%d users)",
                                    len(result))

        local_db = _load_local_db()
        merged   = _merge_db(channel_db, local_db)
        with _db_lock:
            _db_cache = merged

        if len(merged.get("books", [])) > (len(channel_db.get("books", [])) if channel_db else 0):
            _db_executor.submit(_bg_save_db, merged)

        return bool(channel_db)

    except Exception as e:
        logger.error("Failed to load DB index: %s", e)
        local_db = _load_local_db()
        with _db_lock:
            _db_cache = local_db or {"books": [], "users": {}, "custom_courses": {}}
        return False


def load_db() -> dict:
    with _db_lock:
        if _db_cache is not None:
            return _db_cache
    db = {"books": [], "users": {}, "custom_courses": {}, "ai_enabled": True}
    with _db_lock:
        _db_cache = db
    return db


def save_db(db: dict) -> None:
    with _db_lock:
        global _db_cache
        _db_cache = db
    _db_executor.submit(_bg_save_db, db)


def _bg_save_db(db: dict) -> None:
    try:
        path = LOCAL_DB_PATH
        with open(path, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        logger.info("Local DB saved ✅ (%d books)", len(db.get("books", [])))
    except Exception as e:
        logger.error("Failed to save local DB: %s", e)
    if DB_CHANNEL_ID:
        try:
            msg_id, file_id = _upload_to_channel(db, "database.json")
            DB_MSG_IDS["db_msg"]  = msg_id
            DB_MSG_IDS["db_file"] = file_id
            _save_index()
        except Exception as e:
            logger.error("Failed to upload DB to channel: %s", e)


LOCAL_STATES_PATH = os.environ.get("LOCAL_STATES_PATH", "user_choices.json")


def get_state(user_id: int) -> dict:
    with _states_lock:
        if _states_cache is not None:
            return dict(_states_cache.get(str(user_id), {}))
    return {}


def set_state(user_id: int, state: dict) -> None:
    global _states_cache
    with _states_lock:
        if _states_cache is None:
            _states_cache = {}
        _states_cache[str(user_id)] = state
        snapshot = dict(_states_cache)
    _states_executor.submit(_bg_save_states, snapshot)


def clear_state(user_id: int) -> None:
    set_state(user_id, {})


def _bg_save_states(states: dict) -> None:
    try:
        with open(LOCAL_STATES_PATH, "w", encoding="utf-8") as f:
            json.dump(states, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Failed to save states locally: %s", e)
    if DB_CHANNEL_ID:
        try:
            msg_id, file_id = _upload_to_channel(states, "user_choices.json")
            DB_MSG_IDS["states_msg"]  = msg_id
            DB_MSG_IDS["states_file"] = file_id
            _save_index()
        except Exception as e:
            logger.error("Failed to upload states to channel: %s", e)


# ── User helpers ──────────────────────────────────────────────────────────────

def get_user_info(db: dict, user_id: int) -> dict:
    uid = str(user_id)
    if uid not in db.get("users", {}):
        db.setdefault("users", {})[uid] = {}
    return db["users"][uid]


def get_lang(user_id: int) -> str:
    state = get_state(user_id)
    return state.get("lang", "en")


def t(user_id: int, key: str) -> str:
    lang = get_lang(user_id)
    return TEXTS.get(lang, TEXTS["en"]).get(key, TEXTS["en"].get(key, key))


# ── String / emoji helpers ─────────────────────────────────────────────────────

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001f926-\U0001f937"
    "\U00010000-\U0010ffff"
    "\u2640-\u2642"
    "\u2600-\u2B55"
    "\u200d"
    "\u23cf"
    "\u23e9"
    "\u231a"
    "\ufe0f"
    "\u3030"
    "]+",
    flags=re.UNICODE,
)


def strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


def clean_filename(name: str) -> str:
    return re.sub(r"[^\w\s\-.]", "", name).strip()


def _loc_match(a: str, b: str) -> bool:
    return a.lower() == b.lower()


def remove_inline_keyboard(chat_id: int, message_id: int) -> None:
    try:
        bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
    except Exception:
        pass


def format_ai_response(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"*\1*", text)
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"^#{1,6}\s*", "📌 *", line)
        if line.startswith("📌 *"):
            line += "*"
        lines.append(line)
    return "\n".join(lines)


def is_identity_question(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in IDENTITY_KEYWORDS)


def is_special_faculty(faculty: str) -> bool:
    return strip_emoji(faculty).strip() in SPECIAL_FACULTIES


def is_no_semester_faculty(faculty: str) -> bool:
    return strip_emoji(faculty).strip() in NO_SEMESTER_FACULTIES


# ── Faculty / department helpers ──────────────────────────────────────────────

def find_faculty_by_key(fac_key: str) -> str | None:
    fac_list = list(FACULTIES.keys())
    if fac_key.startswith("f") and fac_key[1:].isdigit():
        idx = int(fac_key[1:])
        if 0 <= idx < len(fac_list):
            return fac_list[idx]
    for faculty in FACULTIES:
        clean = strip_emoji(faculty)
        if clean[:len(fac_key)] == fac_key or fac_key in clean:
            return faculty
    return None


def find_faculty_dept_by_key(fac_key: str, dept_key: str) -> tuple[str | None, str | None]:
    fac_list = list(FACULTIES.keys())
    faculty  = None
    if fac_key.startswith("f") and fac_key[1:].isdigit():
        idx = int(fac_key[1:])
        if 0 <= idx < len(fac_list):
            faculty = fac_list[idx]
    if faculty is None:
        for fac in FACULTIES:
            clean_fac = strip_emoji(fac)
            if clean_fac[:len(fac_key)] == fac_key or fac_key in clean_fac:
                faculty = fac
                break
    if faculty is None:
        return None, None
    if not dept_key:
        return faculty, ""
    depts = FACULTIES[faculty]
    if dept_key.startswith("d") and dept_key[1:].isdigit():
        idx = int(dept_key[1:])
        if 0 <= idx < len(depts):
            return faculty, depts[idx]
    for dept in depts:
        clean_dept = strip_emoji(dept)
        if clean_dept[:len(dept_key)] == dept_key or dept_key in clean_dept:
            return faculty, dept
    return None, None


# ── Key helpers ───────────────────────────────────────────────────────────────

def _fac_cb_key(faculty: str) -> str:
    fac_list = list(FACULTIES.keys())
    try:
        idx = fac_list.index(faculty)
        return f"f{idx}"
    except ValueError:
        return strip_emoji(faculty)[:8]


def _dept_cb_key(dept: str) -> str:
    for fac_depts in FACULTIES.values():
        if dept in fac_depts:
            idx = fac_depts.index(dept)
            return f"d{idx}"
    return strip_emoji(dept)[:8]


# ── Keyboards ─────────────────────────────────────────────────────────────────

def main_menu_keyboard(user_id: int) -> types.ReplyKeyboardMarkup:
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.row(types.KeyboardButton(t(user_id, "browse")),
               types.KeyboardButton(t(user_id, "upload")))
    markup.row(types.KeyboardButton(t(user_id, "leaderboard")),
               types.KeyboardButton(t(user_id, "help")))
    markup.row(types.KeyboardButton(t(user_id, "contact")),
               types.KeyboardButton(t(user_id, "mtu_ai")))
    markup.row(types.KeyboardButton(t(user_id, "search")),
               types.KeyboardButton(t(user_id, "request_file")))
    return markup


def ai_keyboard(user_id: int) -> types.ReplyKeyboardMarkup:
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton(t(user_id, "exit_chat")))
    return markup


def language_keyboard() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🇬🇧  English", callback_data="lang_en"),
        types.InlineKeyboardButton("🇪🇹  አማርኛ",  callback_data="lang_am"),
    )
    return markup


def faculty_keyboard(user_id: int, prefix: str = "browse") -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    seen_keys: set[str] = set()
    for faculty in FACULTIES:
        key = _fac_cb_key(faculty)
        if key in seen_keys:
            key = key[:20] + str(len(seen_keys))
        seen_keys.add(key)
        markup.add(
            types.InlineKeyboardButton(
                faculty, callback_data=f"{prefix}_fac_{key}"
            )
        )
    markup.add(types.InlineKeyboardButton(t(user_id, "main_menu_btn"), callback_data="main_menu"))
    return markup


def onboarding_faculty_keyboard(lang: str) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    seen_keys: set[str] = set()
    for faculty in FACULTIES:
        key = _fac_cb_key(faculty)
        if key in seen_keys:
            key = key[:20] + str(len(seen_keys))
        seen_keys.add(key)
        markup.add(
            types.InlineKeyboardButton(
                faculty, callback_data=f"ob_fac_{key}"
            )
        )
    skip_label = "⏭️ Skip (Set up later)" if lang == "en" else "⏭️ ዝለል (ኋላ ማዋቀር)"
    markup.add(types.InlineKeyboardButton(skip_label, callback_data="ob_skip"))
    return markup


def onboarding_dept_keyboard(faculty: str, lang: str) -> types.InlineKeyboardMarkup:
    markup  = types.InlineKeyboardMarkup(row_width=1)
    fac_key = _fac_cb_key(faculty)
    for dept in FACULTIES.get(faculty, []):
        dept_key = _dept_cb_key(dept)
        markup.add(
            types.InlineKeyboardButton(
                dept, callback_data=f"ob_dep_{fac_key}|{dept_key}"
            )
        )
    if not FACULTIES.get(faculty):
        markup.add(
            types.InlineKeyboardButton(
                "✅ Confirm" if lang == "en" else "✅ አረጋግጥ",
                callback_data=f"ob_dep_{fac_key}|"
            )
        )
    back_label = "⬅️ Back" if lang == "en" else "⬅️ ተመለስ"
    skip_label = "⏭️ Skip" if lang == "en" else "⏭️ ዝለል"
    markup.row(
        types.InlineKeyboardButton(back_label, callback_data="ob_back_fac"),
        types.InlineKeyboardButton(skip_label, callback_data="ob_skip"),
    )
    return markup


def onboarding_year_keyboard(faculty: str, dept: str, lang: str) -> types.InlineKeyboardMarkup:
    """Year keyboard used during onboarding — shows only valid years for the dept."""
    markup    = types.InlineKeyboardMarkup(row_width=3)
    fac_key   = _fac_cb_key(faculty)
    dept_key  = _dept_cb_key(dept) if dept else ""
    num_years = get_dept_year_count(dept)
    buttons   = [
        types.InlineKeyboardButton(
            YEARS[i],
            callback_data=f"ob_yr_{fac_key}|{dept_key}|{YEAR_LABELS[i]}"
        )
        for i in range(num_years)
    ]
    markup.add(*buttons)
    back_label = "⬅️ Back" if lang == "en" else "⬅️ ተመለስ"
    skip_label = "⏭️ Skip" if lang == "en" else "⏭️ ዝለል"
    markup.row(
        types.InlineKeyboardButton(back_label, callback_data=f"ob_back_dep_{fac_key}"),
        types.InlineKeyboardButton(skip_label, callback_data="ob_skip"),
    )
    return markup


def department_keyboard(user_id: int, faculty: str, prefix: str = "browse") -> types.InlineKeyboardMarkup:
    markup  = types.InlineKeyboardMarkup(row_width=1)
    fac_key = _fac_cb_key(faculty)
    for dept in FACULTIES.get(faculty, []):
        dept_key = _dept_cb_key(dept)
        markup.add(
            types.InlineKeyboardButton(
                dept, callback_data=f"{prefix}_dep_{fac_key}|{dept_key}"
            )
        )
    markup.add(types.InlineKeyboardButton(t(user_id, "back"), callback_data=f"{prefix}_bk_fac"))
    return markup


def year_keyboard(user_id: int, faculty: str, dept: str, prefix: str = "browse") -> types.InlineKeyboardMarkup:
    markup   = types.InlineKeyboardMarkup(row_width=3)
    fac_key  = _fac_cb_key(faculty)
    dept_key = _dept_cb_key(dept) if dept else ""
    num_years = get_dept_year_count(dept)
    buttons  = [
        types.InlineKeyboardButton(
            YEARS[i], callback_data=f"{prefix}_yr_{fac_key}|{dept_key}|{YEAR_LABELS[i]}"
        )
        for i in range(num_years)
    ]
    markup.add(*buttons)
    markup.add(
        types.InlineKeyboardButton(
            t(user_id, "back"), callback_data=f"{prefix}_bk_dep_{fac_key}"
        )
    )
    return markup


def semester_keyboard(user_id: int, faculty: str, dept: str, year: str,
                      prefix: str = "browse") -> types.InlineKeyboardMarkup:
    markup   = types.InlineKeyboardMarkup(row_width=2)
    fac_key  = _fac_cb_key(faculty)
    dept_key = _dept_cb_key(dept) if dept else ""
    yr_key   = year if year else "direct"
    markup.row(
        types.InlineKeyboardButton(
            "📙 Semester 1",
            callback_data=f"{prefix}_s_{fac_key}|{dept_key}|{yr_key}|Sem1",
        ),
        types.InlineKeyboardButton(
            "📗 Semester 2",
            callback_data=f"{prefix}_s_{fac_key}|{dept_key}|{yr_key}|Sem2",
        ),
    )
    if dept:
        back_cb = f"{prefix}_bk_yr_{fac_key}|{dept_key}"
    else:
        back_cb = f"{prefix}_bk_fac"
    markup.add(types.InlineKeyboardButton(t(user_id, "back"), callback_data=back_cb))
    return markup


# ── Course helpers ────────────────────────────────────────────────────────────

def get_custom_courses(faculty: str, dept: str, year: str, semester: str) -> list[str]:
    db           = load_db()
    fac_clean    = strip_emoji(faculty)
    dept_clean   = strip_emoji(dept) if dept else ""
    location_key = f"{fac_clean}|{dept_clean}|{year}|{semester}"
    return db.get("custom_courses", {}).get(location_key, [])


def get_predefined_courses(faculty: str, dept: str, year: str, semester: str) -> list[str]:
    fac_clean  = strip_emoji(faculty)
    dept_clean = strip_emoji(dept) if dept else ""
    return PREDEFINED_COURSES.get((fac_clean, dept_clean, year, semester), [])


def get_all_courses(faculty: str, dept: str, year: str,
                    semester: str) -> tuple[list[str], list[str]]:
    predefined      = get_predefined_courses(faculty, dept, year, semester)
    custom          = get_custom_courses(faculty, dept, year, semester)
    predefined_lower = {c.lower() for c in predefined}
    unique_custom   = [c for c in custom if c.lower() not in predefined_lower]
    return predefined, unique_custom


def add_custom_course(faculty: str, dept: str, year: str,
                      semester: str, course_name: str) -> bool:
    db = load_db()
    if "custom_courses" not in db:
        db["custom_courses"] = {}
    fac_clean    = strip_emoji(faculty)
    dept_clean   = strip_emoji(dept) if dept else ""
    location_key = f"{fac_clean}|{dept_clean}|{year}|{semester}"
    existing     = db["custom_courses"].get(location_key, [])
    course_clean = course_name.strip()
    predefined   = PREDEFINED_COURSES.get((fac_clean, dept_clean, year, semester), [])
    if any(c.lower() == course_clean.lower() for c in existing + predefined):
        return False
    existing.append(course_clean)
    db["custom_courses"][location_key] = existing
    save_db(db)
    return True


def delete_custom_course(faculty: str, dept: str, year: str,
                         semester: str, course_name: str) -> None:
    db = load_db()
    if "custom_courses" not in db:
        return
    fac_clean    = strip_emoji(faculty)
    dept_clean   = strip_emoji(dept) if dept else ""
    location_key = f"{fac_clean}|{dept_clean}|{year}|{semester}"
    existing     = db["custom_courses"].get(location_key, [])
    db["custom_courses"][location_key] = [
        c for c in existing if c.lower() != course_name.lower()
    ]
    db["books"] = [
        b for b in db["books"]
        if not (
            _loc_match(strip_emoji(b.get("faculty", "")), fac_clean)
            and _loc_match(strip_emoji(b.get("department", "")), dept_clean)
            and b.get("year", "") == year
            and b.get("semester", "") == semester
            and (b.get("course") or "").lower() == course_name.lower()
        )
    ]
    save_db(db)


# ── Course listing / upload keyboards ─────────────────────────────────────────

def course_listing_keyboard(user_id: int, faculty: str, dept: str,
                             year: str, semester: str) -> types.InlineKeyboardMarkup:
    markup   = types.InlineKeyboardMarkup(row_width=1)
    fac_key  = _fac_cb_key(faculty)
    dept_key = _dept_cb_key(dept) if dept else ""
    yr_key   = year if year else "direct"

    markup.add(
        types.InlineKeyboardButton(
            t(user_id, "general_files"),
            callback_data=f"crs_gen_{fac_key}|{dept_key}|{yr_key}|{semester}",
        )
    )

    predefined, unique_custom = get_all_courses(faculty, dept, year, semester)
    for course in predefined:
        safe = course[:20].replace("|", "-")
        markup.add(
            types.InlineKeyboardButton(
                f"📘 {course}",
                callback_data=f"crs_c_{fac_key}|{dept_key}|{yr_key}|{semester}|{safe}",
            )
        )
    for course in unique_custom:
        safe = course[:20].replace("|", "-")
        markup.add(
            types.InlineKeyboardButton(
                f"📖 {course}",
                callback_data=f"crs_c_{fac_key}|{dept_key}|{yr_key}|{semester}|{safe}",
            )
        )

    markup.add(
        types.InlineKeyboardButton(
            t(user_id, "create_course"),
            callback_data=f"crs_create_{fac_key}|{dept_key}|{yr_key}|{semester}",
        )
    )
    back_cb = f"browse_bk_sem_{fac_key}|{dept_key}|{yr_key}"
    markup.row(
        types.InlineKeyboardButton(t(user_id, "back"), callback_data=back_cb),
        types.InlineKeyboardButton(t(user_id, "main_menu_btn"), callback_data="main_menu"),
    )
    return markup


def _assert_cb_len(cb: str, context: str = "") -> str:
    if len(cb.encode("utf-8")) > 64:
        raise ValueError(
            f"callback_data too long ({len(cb.encode())} bytes) in {context}: {cb!r}"
        )
    return cb


def upload_course_keyboard(user_id: int, faculty: str, dept: str,
                           year: str, semester: str) -> types.InlineKeyboardMarkup:
    markup   = types.InlineKeyboardMarkup(row_width=1)
    fac_key  = _fac_cb_key(faculty)
    dept_key = _dept_cb_key(dept) if dept else ""
    yr_key   = year if year else "direct"

    markup.add(
        types.InlineKeyboardButton(
            t(user_id, "general_files"),
            callback_data=f"upload_crs_gen_{fac_key}|{dept_key}|{yr_key}|{semester}",
        )
    )

    predefined, unique_custom = get_all_courses(faculty, dept, year, semester)
    for course in predefined:
        safe = course[:20].replace("|", "-")
        markup.add(
            types.InlineKeyboardButton(
                f"📘 {course}",
                callback_data=f"upload_crs_{fac_key}|{dept_key}|{yr_key}|{semester}|{safe}",
            )
        )
    for course in unique_custom:
        safe = course[:20].replace("|", "-")
        markup.add(
            types.InlineKeyboardButton(
                f"📖 {course}",
                callback_data=f"upload_crs_{fac_key}|{dept_key}|{yr_key}|{semester}|{safe}",
            )
        )

    markup.add(
        types.InlineKeyboardButton(
            t(user_id, "create_course"),
            callback_data=f"upload_crs_create_{fac_key}|{dept_key}|{yr_key}|{semester}",
        )
    )
    back_cb = f"upload_bk_sem_{fac_key}|{dept_key}|{yr_key}"
    markup.add(
        types.InlineKeyboardButton(
            t(user_id, "back"),
            callback_data=back_cb,
        )
    )
    return markup


def books_keyboard(user_id: int, books: list, faculty: str, dept: str,
                   year: str, semester: str, course: str | None = None) -> types.InlineKeyboardMarkup:
    markup     = types.InlineKeyboardMarkup(row_width=1)
    fac_key    = _fac_cb_key(faculty)
    dept_key   = _dept_cb_key(dept) if dept else ""
    yr_key     = year if year else "direct"
    icons      = ["📗", "📘", "📙", "📕", "📓", "📔", "📒", "📃", "📄", "📑"]

    for idx, book in enumerate(books):
        stars   = book.get("stars", 0)
        voters  = len(book.get("voters", []))
        avg     = round(stars / voters) if voters > 0 else 0
        icon    = icons[idx % len(icons)]
        star_d  = "⭐" * avg if avg > 0 else "☆"
        name    = book["file_name"].replace("_", " ").title()[:22]
        label   = f"{icon} {name} {star_d}"
        tg_file_id = book.get("telegram_file_id", "")
        cb = f"dlf_{tg_file_id[:30]}"
        markup.add(types.InlineKeyboardButton(label, callback_data=cb))

    if is_no_semester_faculty(faculty):
        back_cb = "browse_bk_fac"
    else:
        back_cb = f"browse_s_{fac_key}|{dept_key}|{yr_key}|{semester}"

    markup.row(
        types.InlineKeyboardButton(t(user_id, "back"), callback_data=back_cb),
        types.InlineKeyboardButton(t(user_id, "main_menu_btn"), callback_data="main_menu"),
    )
    return markup


def rating_keyboard(user_id: int, tg_file_id: str) -> types.InlineKeyboardMarkup:
    markup  = types.InlineKeyboardMarkup(row_width=5)
    safe_id = tg_file_id[:28]
    buttons = [
        types.InlineKeyboardButton(
            t(user_id, f"rate_{i}"),
            callback_data=f"rt_{i}_{safe_id}",
        )
        for i in range(1, 6)
    ]
    markup.add(*buttons)
    markup.row(types.InlineKeyboardButton("⏭️ Skip", callback_data="main_menu"))
    return markup


# ── Book query helpers ────────────────────────────────────────────────────────

def get_books_for(faculty: str, dept: str, year: str, semester: str,
                  course: str | None = None) -> list[dict]:
    db         = load_db()
    fac_clean  = strip_emoji(faculty)
    dept_clean = strip_emoji(dept) if dept else ""
    no_sem     = is_no_semester_faculty(faculty)
    result     = []
    for b in db["books"]:
        b_fac    = strip_emoji(b.get("faculty", ""))
        b_dept   = strip_emoji(b.get("department", ""))
        b_yr     = b.get("year", "")
        b_sem    = b.get("semester", "")
        b_course = b.get("course", None)
        if (_loc_match(b_fac, fac_clean)
                and _loc_match(b_dept, dept_clean)
                and b_yr == year
                and (no_sem or b_sem == semester)):
            if course is None:
                result.append(b)
            elif course == "__unordered__":
                if not b_course:
                    result.append(b)
            else:
                if b_course and b_course.lower() == course.lower():
                    result.append(b)
    return result


def get_unordered_books() -> list[dict]:
    db = load_db()
    return [b for b in db["books"] if not b.get("course")]


# ── Department notification helper ────────────────────────────────────────────

def _notify_department_users(uploader_id: int, fac_clean: str, dept_clean: str,
                              year: str, semester: str, file_name: str) -> None:
    """Notify users whose department AND year match the uploaded file."""
    if not fac_clean or not dept_clean:
        return
    db = load_db()
    sem_label    = "Semester 1" if semester == "Sem1" else ("Semester 2" if semester == "Sem2" else "")
    file_display = file_name.replace("_", " ").title()[:40]

    for uid_str, info in db.get("users", {}).items():
        try:
            uid = int(uid_str)
        except (ValueError, TypeError):
            continue
        if uid == uploader_id:
            continue
        user_fac  = strip_emoji(info.get("faculty", ""))
        user_dept = strip_emoji(info.get("department", ""))
        user_year = info.get("year", "")
        if not user_fac or not user_dept:
            continue
        if not (_loc_match(user_fac, fac_clean) and _loc_match(user_dept, dept_clean)):
            continue
        # Year filter: if user has a year set, only notify if it matches
        if user_year and year and user_year != year:
            continue
        notif_parts = [f"📚 *{dept_clean}*"]
        if year:
            notif_parts.append(year)
        if sem_label:
            notif_parts.append(sem_label)
        location_line = " · ".join(notif_parts)
        lang = info.get("lang", "en")
        if lang == "am":
            msg = (
                f"🔔 *አዲስ ፋይል ለዲፓርትመንትዎ!*\n"
                f"{DIVIDER}\n"
                f"📄 *{file_display}*\n"
                f"📍 {location_line}"
            )
        else:
            msg = (
                f"🔔 *New file in your department!*\n"
                f"{DIVIDER}\n"
                f"📄 *{file_display}*\n"
                f"📍 {location_line}"
            )
        try:
            bot.send_message(uid, msg, parse_mode="Markdown")
            time.sleep(0.05)
        except Exception as notify_err:
            logger.warning("Dept notification failed for %s: %s", uid_str, notify_err)


# ── Bot command handlers ──────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(message):
    user_id = message.from_user.id
    clear_state(user_id)
    bot.send_message(
        user_id,
        TEXTS["en"]["welcome"],
        reply_markup=language_keyboard(),
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["aicheck"])
def cmd_aicheck(message):
    user_id = message.from_user.id
    if user_id != OWNER_ID:
        return
    status = (
        f"🔍 *AI Diagnostic*\n"
        f"{DIVIDER}\n"
        f"📦 Package: {'✅ google-genai' if GEMINI_AVAILABLE else '❌ Not installed'}\n"
        f"🔑 API keys: *{len(GOOGLE_API_KEYS)}*\n"
        f"🤖 AI Enabled: {'✅ Yes' if is_ai_enabled() else '❌ No (disabled by admin)'}\n"
    )
    bot.send_message(user_id, status, parse_mode="Markdown")
    if not GEMINI_AVAILABLE or not GOOGLE_API_KEYS:
        return
    bot.send_message(user_id, "⏳ Listing available models on your first API key…")
    api_key = GOOGLE_API_KEYS[0]
    try:
        client = genai.Client(api_key=api_key)
        models = client.models.list()
        names  = [m.name for m in models if "generateContent" in (m.supported_actions or [])]
        if names:
            bot.send_message(user_id,
                f"✅ *Available models:*\n```\n{chr(10).join(names[:20])}\n```",
                parse_mode="Markdown")
        else:
            all_names = [m.name for m in models][:20]
            bot.send_message(user_id,
                f"⚠️ No generateContent models found.\n*All:*\n```\n{chr(10).join(all_names)}\n```",
                parse_mode="Markdown")
    except Exception as e:
        bot.send_message(user_id, f"❌ Model listing failed:\n`{str(e)[:500]}`",
                         parse_mode="Markdown")


@bot.message_handler(commands=["admin6843"])
def cmd_admin(message):
    user_id = message.from_user.id
    if user_id != OWNER_ID:
        bot.send_message(user_id, t(user_id, "not_admin"))
        return
    db         = load_db()
    ai_status  = "✅ ON" if is_ai_enabled() else "❌ OFF"
    text = (
        f"🔧 *Admin Panel*\n"
        f"{DIVIDER}\n"
        f"📚 Total Books: *{len(db['books'])}*\n"
        f"👤 Total Users: *{len(db['users'])}*\n"
        f"🔑 Active Gemini Keys: *{len(GOOGLE_API_KEYS)}*\n"
        f"🤖 AI Status: *{ai_status}*\n"
        f"{DIVIDER}"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 Books",       callback_data="admin_list_books"),
        types.InlineKeyboardButton("👥 Users",       callback_data="admin_list_users"),
    )
    markup.add(
        types.InlineKeyboardButton("🗑️ Delete Book",   callback_data="admin_delete_prompt"),
        types.InlineKeyboardButton("📂 Delete Course",  callback_data="admin_delete_course_prompt"),
    )
    markup.add(
        types.InlineKeyboardButton("📢 Broadcast",     callback_data="admin_broadcast_prompt"),
        types.InlineKeyboardButton("✉️ Direct Message", callback_data="admin_dm_prompt"),
    )
    if is_ai_enabled():
        markup.add(types.InlineKeyboardButton("🔴 Stop AI",  callback_data="admin_ai_disable"))
    else:
        markup.add(types.InlineKeyboardButton("🟢 Start AI", callback_data="admin_ai_enable"))
    bot.send_message(user_id, text, reply_markup=markup, parse_mode="Markdown")


@bot.message_handler(commands=["search"])
def cmd_search(message):
    user_id = message.from_user.id
    state = get_state(user_id)
    state["action"] = ACTION_SEARCH
    set_state(user_id, state)
    bot.send_message(user_id, t(user_id, "search_prompt"), parse_mode="Markdown")


# ── Language selection ────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data.startswith("lang_"))
def cb_language(call):
    user_id = call.from_user.id
    lang    = call.data.split("_")[1]
    state   = get_state(user_id)
    state["lang"]   = lang
    state["action"] = ACTION_ONBOARDING_FAC
    set_state(user_id, state)
    db        = load_db()
    user_info = get_user_info(db, user_id)
    fname     = call.from_user.first_name or ""
    lname     = call.from_user.last_name  or ""
    full_name = (fname + " " + lname).strip() or str(user_id)
    user_info["name"] = full_name
    user_info["lang"] = lang
    save_db(db)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)

    greet = (f"👋 *Hello, {full_name}!*\n\n" if lang == "en"
             else f"👋 *ሰላም, {full_name}!*\n\n")
    onboarding_text = greet + TEXTS[lang]["onboarding_faculty"]
    bot.send_message(
        user_id,
        onboarding_text,
        reply_markup=onboarding_faculty_keyboard(lang),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


# ── Onboarding callbacks ──────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data == "ob_skip")
def cb_onboarding_skip(call):
    user_id = call.from_user.id
    state   = get_state(user_id)
    state["action"] = None
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(
        user_id,
        t(user_id, "main_menu"),
        reply_markup=main_menu_keyboard(user_id),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "ob_back_fac")
def cb_onboarding_back_fac(call):
    user_id = call.from_user.id
    lang    = get_lang(user_id)
    state   = get_state(user_id)
    state["action"] = ACTION_ONBOARDING_FAC
    state.pop("ob_faculty", None)
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(
        user_id,
        TEXTS[lang]["onboarding_faculty"],
        reply_markup=onboarding_faculty_keyboard(lang),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("ob_back_dep_"))
def cb_onboarding_back_dep(call):
    """Back from year selection → go back to department selection."""
    user_id = call.from_user.id
    fac_key = call.data.replace("ob_back_dep_", "")
    faculty = find_faculty_by_key(fac_key)
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    lang  = get_lang(user_id)
    state = get_state(user_id)
    state["action"]     = ACTION_ONBOARDING_DEPT
    state["ob_faculty"] = faculty
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(
        user_id,
        TEXTS[lang]["onboarding_dept"],
        reply_markup=onboarding_dept_keyboard(faculty, lang),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("ob_fac_"))
def cb_onboarding_faculty(call):
    user_id = call.from_user.id
    fac_key = call.data.replace("ob_fac_", "")
    faculty = find_faculty_by_key(fac_key)
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    lang  = get_lang(user_id)
    state = get_state(user_id)
    state["ob_faculty"] = faculty
    state["action"]     = ACTION_ONBOARDING_DEPT
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)

    # For faculties with no departments (Freshman, Remedial), skip directly to year
    if not FACULTIES.get(faculty):
        _save_user_profile(user_id, faculty, "", "")
        state["action"] = None
        set_state(user_id, state)
        done_msg = TEXTS[lang]["onboarding_done_am" if lang == "am" else "onboarding_done_en"]
        bot.send_message(
            user_id,
            done_msg + "\n\n" + t(user_id, "main_menu"),
            reply_markup=main_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
        bot.answer_callback_query(call.id)
        return

    bot.send_message(
        user_id,
        TEXTS[lang]["onboarding_dept"],
        reply_markup=onboarding_dept_keyboard(faculty, lang),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("ob_dep_"))
def cb_onboarding_dept(call):
    user_id  = call.from_user.id
    raw      = call.data.replace("ob_dep_", "")
    parts    = raw.split("|", 1)
    fac_key  = parts[0]
    dept_key = parts[1] if len(parts) > 1 else ""
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    lang  = get_lang(user_id)
    state = get_state(user_id)
    state["ob_faculty"] = faculty
    state["ob_dept"]    = dept or ""
    state["action"]     = ACTION_ONBOARDING_YEAR
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)

    # Ask for year selection
    bot.send_message(
        user_id,
        TEXTS[lang]["onboarding_year"],
        reply_markup=onboarding_year_keyboard(faculty, dept or "", lang),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("ob_yr_"))
def cb_onboarding_year(call):
    user_id = call.from_user.id
    raw     = call.data.replace("ob_yr_", "")
    parts   = raw.split("|", 2)
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, year_label = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    lang  = get_lang(user_id)
    _save_user_profile(user_id, faculty, dept or "", year_label)
    state           = get_state(user_id)
    state["action"] = None
    state.pop("ob_faculty", None)
    state.pop("ob_dept", None)
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    done_msg = TEXTS[lang]["onboarding_done_am" if lang == "am" else "onboarding_done_en"]
    bot.send_message(
        user_id,
        done_msg + "\n\n" + t(user_id, "main_menu"),
        reply_markup=main_menu_keyboard(user_id),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


def _save_user_profile(user_id: int, faculty: str, dept: str, year: str = "") -> None:
    """Persist faculty, department and year into the user record in db."""
    db        = load_db()
    user_info = get_user_info(db, user_id)
    fac_clean  = strip_emoji(faculty)
    dept_clean = strip_emoji(dept) if dept else ""
    user_info["faculty"]    = fac_clean
    user_info["department"] = dept_clean
    user_info["lang"]       = get_lang(user_id)
    if year:
        user_info["year"] = year
    save_db(db)
    logger.info("User %s profile saved: fac=%s dept=%s year=%s",
                user_id, fac_clean, dept_clean, year)


@bot.callback_query_handler(func=lambda call: call.data == "main_menu")
def cb_main_menu(call):
    user_id = call.from_user.id
    state   = get_state(user_id)
    state["action"] = None
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(
        user_id,
        t(user_id, "main_menu"),
        reply_markup=main_menu_keyboard(user_id),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


# ── AI – model rotation and worker ────────────────────────────────────────────

_AI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite-001",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
]

_sticky_model      = None
_sticky_model_lock = threading.Lock()


def _get_model_order() -> list[str]:
    with _sticky_model_lock:
        sticky = _sticky_model
    if sticky and sticky in _AI_MODELS:
        return [sticky] + [m for m in _AI_MODELS if m != sticky]
    return list(_AI_MODELS)


def _set_sticky_model(model: str) -> None:
    global _sticky_model
    with _sticky_model_lock:
        if _sticky_model != model:
            logger.info("Sticky model → %s", model)
            _sticky_model = model


def _clear_sticky_model() -> None:
    global _sticky_model
    with _sticky_model_lock:
        if _sticky_model is not None:
            logger.info("Sticky model cleared (failed)")
            _sticky_model = None


_KEY_BAD_SIGNALS = (
    "quota", "rate limit", "429", "resource exhausted",
    "invalid api key", "api key not valid", "api_key_invalid",
    "authentication", "permission denied", "forbidden", "401", "403",
)
_NETWORK_SIGNALS = (
    "connection", "timeout", "timed out", "network", "reset by peer",
    "eof occurred", "broken pipe", "remote end closed", "502", "503", "504",
)


class _KeyBadError(Exception):
    pass


def _is_key_bad(err_str: str) -> bool:
    return any(s in err_str for s in _KEY_BAD_SIGNALS)


def _is_network_err(err_str: str) -> bool:
    return any(s in err_str for s in _NETWORK_SIGNALS)


def _build_contents(history: list, prompt: str) -> list:
    contents = []
    for turn in history:
        role      = turn.get("role", "user")
        parts_raw = turn.get("parts", [])
        parts     = [
            genai_types.Part(text=p) if isinstance(p, str) else p
            for p in parts_raw
        ]
        contents.append(genai_types.Content(role=role, parts=parts))
    contents.append(genai_types.Content(
        role="user", parts=[genai_types.Part(text=prompt)]
    ))
    return contents


def _try_models(client, contents: list, label: str) -> str | None:
    for model_name in _get_model_order():
        for attempt in range(3):
            try:
                cfg  = genai_types.GenerateContentConfig(
                    system_instruction=AI_SYSTEM_PROMPT,
                    temperature=0.7,
                    max_output_tokens=800,
                )
                resp = client.models.generate_content(
                    model=model_name, contents=contents, config=cfg
                )
                text = ""
                if resp.candidates:
                    cand   = resp.candidates[0]
                    finish = str(getattr(cand, "finish_reason", "") or "").upper()
                    if finish in ("SAFETY", "2"):
                        logger.warning("%s model=%s safety block", label, model_name)
                        return None
                    if cand.content and cand.content.parts:
                        text = "".join(
                            p.text for p in cand.content.parts
                            if hasattr(p, "text") and p.text
                        )
                if text:
                    _set_sticky_model(model_name)
                    return text
                break
            except Exception as e:
                err_str = str(e).lower()
                if _is_key_bad(err_str):
                    raise _KeyBadError(str(e))
                if _is_network_err(err_str) and attempt < 2:
                    time.sleep(2)
                    continue
                logger.warning("%s model=%s attempt=%d err=%s",
                               label, model_name, attempt + 1, e)
                break
    _clear_sticky_model()
    return ""


def _nuclear_fallback(user_text: str) -> str:
    for api_key in GOOGLE_API_KEYS:
        try:
            client = genai.Client(api_key=api_key)
        except Exception:
            continue
        for model_name in _AI_MODELS:
            try:
                resp = client.models.generate_content(
                    model=model_name, contents=user_text
                )
                text = ""
                if resp.candidates:
                    cand = resp.candidates[0]
                    if cand.content and cand.content.parts:
                        text = "".join(
                            p.text for p in cand.content.parts
                            if hasattr(p, "text") and p.text
                        )
                if text:
                    _set_sticky_model(model_name)
                    return text
            except Exception:
                continue
    return ""


def _send_ai_reply(user_id: int, raw: str) -> None:
    formatted = format_ai_response(raw)
    header    = f"🤖 *mtu.ai*\n{DIVIDER}\n"
    try:
        bot.send_message(user_id, header + formatted, parse_mode="Markdown")
    except Exception:
        try:
            bot.send_message(user_id, "🤖 mtu.ai\n" + raw[:3800])
        except Exception:
            try:
                bot.send_message(user_id, raw[:2000])
            except Exception:
                pass


def _ai_worker(user_id: int, user_text: str, lang: str,
               history: list, prompt: str, thinking_msg) -> None:
    raw               = ""
    succeeded         = False
    final_safety      = False
    keys_seen: set[str] = set()

    for global_round in range(3):
        if global_round > 0:
            delay = global_round * 5
            logger.info("AI global retry round %d/3 — waiting %ds (user %s)",
                        global_round + 1, delay, user_id)
            time.sleep(delay)

        for _ki in range(len(GOOGLE_API_KEYS)):
            api_key = get_next_api_key()
            if not api_key or api_key in keys_seen:
                continue
            keys_seen.add(api_key)

            try:
                client = genai.Client(api_key=api_key)
            except Exception as e:
                logger.error("Client creation failed: %s", e)
                continue

            label = f"R{global_round+1} k{_ki+1}/{len(GOOGLE_API_KEYS)}"

            try:
                result = _try_models(client, _build_contents(history, prompt), label + "+hist")
                if result:
                    raw, succeeded = result, True
                elif result is None:
                    final_safety = True
            except _KeyBadError as e:
                logger.warning("%s key bad (p1): %s", label, e)
                continue

            if succeeded or final_safety:
                break

            try:
                result = _try_models(client, _build_contents([], prompt), label + "-hist")
                if result:
                    raw, succeeded = result, True
                    with ai_histories_lock:
                        ai_chat_histories[user_id] = []
                elif result is None:
                    final_safety = True
            except _KeyBadError as e:
                logger.warning("%s key bad (p2): %s", label, e)
                continue

            if succeeded or final_safety:
                break

            try:
                bare   = [genai_types.Content(role="user",
                           parts=[genai_types.Part(text=user_text)])]
                result = _try_models(client, bare, label + " bare")
                if result:
                    raw, succeeded = result, True
                elif result is None:
                    final_safety = True
            except _KeyBadError as e:
                logger.warning("%s key bad (p3): %s", label, e)
                continue

            if succeeded or final_safety:
                break

        if succeeded or final_safety:
            break

    if not succeeded and not final_safety:
        logger.warning("All passes failed for user %s — nuclear fallback", user_id)
        raw = _nuclear_fallback(user_text)
        if raw:
            succeeded = True

    if thinking_msg:
        try:
            bot.delete_message(user_id, thinking_msg.message_id)
        except Exception:
            pass

    if succeeded and raw:
        with ai_histories_lock:
            hist = ai_chat_histories.setdefault(user_id, [])
            hist.append({"role": "user",  "parts": [prompt]})
            hist.append({"role": "model", "parts": [raw]})
            if len(hist) > 40:
                ai_chat_histories[user_id] = hist[-40:]
        _send_ai_reply(user_id, raw)

    elif final_safety:
        try:
            bot.send_message(
                user_id,
                "⚠️ Your question was blocked by the AI safety filter.\n"
                "Please rephrase it and try again.",
                reply_markup=ai_keyboard(user_id),
            )
        except Exception:
            pass
    else:
        logger.error("All AI strategies (incl. nuclear) exhausted for user %s", user_id)
        try:
            bot.send_message(user_id, t(user_id, "ai_error"),
                             reply_markup=ai_keyboard(user_id))
        except Exception:
            pass


def handle_ai_message(message) -> None:
    user_id = message.from_user.id
    lang    = get_lang(user_id)

    if not is_ai_enabled():
        msg = MTU_AI_COMING_SOON_EN if lang == "en" else MTU_AI_COMING_SOON_AM
        bot.send_message(user_id, msg, parse_mode="Markdown")
        return

    user_text = (getattr(message, "text", None) or "").strip()
    if not user_text:
        bot.send_message(user_id,
                         "Please send a text message for mtu.ai 💬",
                         reply_markup=ai_keyboard(user_id))
        return

    if is_identity_question(user_text):
        resp = IDENTITY_RESPONSE_EN if lang == "en" else IDENTITY_RESPONSE_AM
        bot.send_message(user_id, resp, parse_mode="Markdown")
        return

    if not GEMINI_AVAILABLE or not GOOGLE_API_KEYS:
        bot.send_message(user_id, t(user_id, "ai_no_key"))
        return

    thinking_msg = None
    try:
        thinking_msg = bot.send_message(user_id, t(user_id, "ai_thinking"),
                                        parse_mode="Markdown")
    except Exception:
        pass

    with ai_histories_lock:
        history = list(ai_chat_histories.get(user_id, []))

    prompt = user_text
    if lang == "am":
        prompt = "Please respond in Amharic (አማርኛ). Question: " + user_text

    threading.Thread(
        target=_ai_worker,
        args=(user_id, user_text, lang, history, prompt, thinking_msg),
        daemon=True,
    ).start()


# ── Leaderboard & Help ────────────────────────────────────────────────────────

def show_leaderboard(user_id: int) -> None:
    db = load_db()
    sorted_users = sorted(
        db.get("users", {}).items(),
        key=lambda x: (x[1].get("uploaded_books", 0), x[1].get("stars_received", 0)),
        reverse=True,
    )
    if not sorted_users:
        bot.send_message(user_id, t(user_id, "leaderboard_empty"),
                         reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
        return
    text = t(user_id, "leaderboard_title")
    for i, (uid, info) in enumerate(sorted_users[:10]):
        medal   = MEDALS[i]
        name    = (info.get("name", uid) or uid)[:16]
        books   = info.get("uploaded_books", 0)
        stars   = info.get("stars_received", 0)
        text   += f"{medal} *{name}*  {t(user_id,'books')}{books} {t(user_id,'stars')}{stars}\n"
    text += f"\n{DIVIDER}"
    bot.send_message(user_id, text, reply_markup=main_menu_keyboard(user_id),
                     parse_mode="Markdown")


def show_help(user_id: int) -> None:
    bot.send_message(user_id, t(user_id, "help_text"),
                     reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")


# ── Contact ───────────────────────────────────────────────────────────────────

def send_contact_message(message) -> None:
    user_id   = message.from_user.id
    db        = load_db()
    name      = get_user_info(db, user_id).get("name", str(user_id))
    msg_text  = (
        f"📨 *New Message from Student*\n"
        f"{DIVIDER}\n"
        f"👤 *{name}*\n"
        f"🆔 `{user_id}`\n"
        f"{DIVIDER}\n"
        f"💬 {message.text}\n"
        f"{DIVIDER}\n"
        f"_Reply to this message to respond to the student._"
    )
    state           = get_state(user_id)
    state["action"] = None
    set_state(user_id, state)
    try:
        sent = bot.send_message(OWNER_ID, msg_text, parse_mode="Markdown")
        with pending_reply_lock:
            pending_reply_targets[sent.message_id] = user_id
        bot.send_message(user_id, t(user_id, "contact_sent"),
                         reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
    except Exception as e:
        logger.error("Contact forward failed: %s", e)
        bot.send_message(user_id, t(user_id, "contact_error"),
                         reply_markup=main_menu_keyboard(user_id))


@bot.message_handler(
    func=lambda msg: msg.from_user.id == OWNER_ID and msg.reply_to_message is not None,
    content_types=["text"]
)
def handle_owner_reply(message):
    replied_to_id = message.reply_to_message.message_id
    with pending_reply_lock:
        target_user_id = pending_reply_targets.get(replied_to_id)
    if not target_user_id:
        return
    try:
        reply_text = f"📩 *Reply from Owner*\n{DIVIDER}\n{message.text}"
        bot.send_message(target_user_id, reply_text, parse_mode="Markdown")
        bot.send_message(OWNER_ID, f"✅ *Reply sent* to user `{target_user_id}`",
                         parse_mode="Markdown")
    except Exception as e:
        logger.error("Failed to forward owner reply: %s", e)
        bot.send_message(OWNER_ID, f"❌ Failed to send reply: {e}")


def send_owner_reply(message, target_user_id: int) -> None:
    state = get_state(OWNER_ID)
    state["action"] = None
    state.pop("dm_target", None)
    set_state(OWNER_ID, state)
    with pending_reply_lock:
        pending_reply_targets.pop(OWNER_ID, None)
    try:
        reply_text = f"📩 *Reply from Owner*\n{DIVIDER}\n{message.text}"
        bot.send_message(target_user_id, reply_text, parse_mode="Markdown")
        bot.send_message(OWNER_ID, f"✅ *Reply sent* to user `{target_user_id}`",
                         reply_markup=main_menu_keyboard(OWNER_ID), parse_mode="Markdown")
    except Exception as e:
        logger.error("Failed to send owner reply: %s", e)
        bot.send_message(OWNER_ID, f"❌ Failed to send reply: {e}")


# ── Broadcast & DM ───────────────────────────────────────────────────────────

def do_broadcast(message) -> None:
    state = get_state(OWNER_ID)
    state["action"] = None
    set_state(OWNER_ID, state)
    db         = load_db()
    user_ids   = list(db.get("users", {}).keys())
    bcast_text = f"📢 *Announcement*\n{DIVIDER}\n{message.text}"
    success, failed = 0, 0
    for uid_str in user_ids:
        try:
            bot.send_message(int(uid_str), bcast_text, parse_mode="Markdown")
            success += 1
            time.sleep(0.05)
        except Exception as e:
            logger.warning("Broadcast failed for %s: %s", uid_str, e)
            failed += 1
    bot.send_message(
        OWNER_ID,
        f"📢 *Broadcast Done*\n{DIVIDER}\n✅ Sent: *{success}*\n❌ Failed: *{failed}*",
        reply_markup=main_menu_keyboard(OWNER_ID), parse_mode="Markdown",
    )


def handle_admin_dm_target(message) -> None:
    state         = get_state(OWNER_ID)
    target_id_str = message.text.strip()
    try:
        target_id = int(target_id_str)
    except ValueError:
        bot.send_message(OWNER_ID, "❌ Invalid user ID. Please send a valid numeric ID.")
        return
    state["action"]    = ACTION_ADMIN_DM_MESSAGE
    state["dm_target"] = target_id
    set_state(OWNER_ID, state)
    bot.send_message(
        OWNER_ID,
        f"✉️ *Direct Message*\n{DIVIDER}\n"
        f"Target: `{target_id}`\n\nType the message to send:",
        parse_mode="Markdown",
    )


def handle_admin_dm_message(message) -> None:
    state     = get_state(OWNER_ID)
    target_id = state.get("dm_target")
    state["action"] = None
    state.pop("dm_target", None)
    set_state(OWNER_ID, state)
    if not target_id:
        bot.send_message(OWNER_ID, "❌ No target user set. Please try again.")
        return
    try:
        dm_text = f"📩 *Message from Owner*\n{DIVIDER}\n{message.text}"
        bot.send_message(int(target_id), dm_text, parse_mode="Markdown")
        bot.send_message(OWNER_ID, f"✅ *Message sent* to `{target_id}`",
                         reply_markup=main_menu_keyboard(OWNER_ID), parse_mode="Markdown")
    except Exception as e:
        logger.error("DM failed: %s", e)
        bot.send_message(OWNER_ID, f"❌ Failed to send message: {e}")


# ── Search ────────────────────────────────────────────────────────────────────

def handle_search(message) -> None:
    user_id = message.from_user.id
    query   = message.text.strip().lower()
    state   = get_state(user_id)
    state["action"] = None
    set_state(user_id, state)

    if not query:
        bot.send_message(user_id, t(user_id, "search_no_results"),
                         reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
        return

    db      = load_db()
    results = [b for b in db["books"] if query in b["file_name"].lower()]

    if not results:
        bot.send_message(user_id, t(user_id, "search_no_results"),
                         reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    icons  = ["📗", "📘", "📙", "📕", "📓", "📔", "📒", "📃", "📄", "📑",
              "📗", "📘", "📙", "📕", "📓"]
    for i, book in enumerate(results[:15]):
        stars    = book.get("stars", 0)
        voters   = len(book.get("voters", []))
        avg      = round(stars / voters) if voters > 0 else 0
        star_str = "⭐" * avg if avg > 0 else "☆"
        name     = book["file_name"].replace("_", " ").title()[:20]
        yr       = book.get("year", "")
        sem      = book.get("semester", "")
        course   = book.get("course", "")
        loc_parts = [p for p in [yr, sem, course] if p]
        loc      = " · ".join(loc_parts) if loc_parts else "General"
        label    = f"{icons[i]} {name} · {loc} {star_str}"
        tg_fid   = book.get("telegram_file_id", "")
        markup.add(types.InlineKeyboardButton(label, callback_data=f"dlf_{tg_fid[:30]}"))
    markup.add(types.InlineKeyboardButton(t(user_id, "main_menu_btn"), callback_data="main_menu"))
    bot.send_message(user_id, t(user_id, "search_results"),
                     reply_markup=markup, parse_mode="Markdown")


# ── Admin delete ──────────────────────────────────────────────────────────────

def handle_admin_delete(message) -> None:
    user_id   = message.from_user.id
    if user_id != OWNER_ID:
        return
    file_name = message.text.strip().lower()
    db        = load_db()
    before    = len(db["books"])
    db["books"] = [b for b in db["books"] if b["file_name"].lower() != file_name]
    state = get_state(user_id)
    state["action"] = None
    set_state(user_id, state)
    if len(db["books"]) < before:
        save_db(db)
        bot.send_message(user_id, f"✅ *Deleted:* `{file_name}`",
                         reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
    else:
        bot.send_message(user_id, f"❌ *Not found:* `{file_name}`\nCheck the exact file name.",
                         reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")


def handle_admin_delete_course_input(message) -> None:
    user_id = message.from_user.id
    if user_id != OWNER_ID:
        return
    text  = message.text.strip()
    state = get_state(user_id)
    state["action"] = None
    set_state(user_id, state)
    parts = text.split("|", 4)
    if len(parts) != 5:
        bot.send_message(
            user_id,
            "❌ Invalid format. Use:\n`FacultyKey|DeptKey|Year|Semester|CourseName`\n\n"
            "Example:\n`Engineering|Software Engineering|Year2|Sem1|Calculus I`",
            parse_mode="Markdown", reply_markup=main_menu_keyboard(user_id),
        )
        return
    fac_key, dept_key, year, semester, course_name = parts
    faculty, dept = find_faculty_dept_by_key(fac_key.strip(), dept_key.strip())
    if not faculty:
        faculty, dept = fac_key.strip(), dept_key.strip()
    delete_custom_course(faculty, dept, year.strip(), semester.strip(), course_name.strip())
    bot.send_message(
        user_id,
        f"✅ *Course deleted:* `{course_name.strip()}`\n"
        f"All files in this course have also been removed.",
        reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown",
    )


# ── Custom course creation (browse flow) ─────────────────────────────────────

def handle_course_name_input(message) -> None:
    user_id     = message.from_user.id
    course_name = message.text.strip()
    state       = get_state(user_id)
    faculty     = state.get("create_course_faculty", "")
    dept        = state.get("create_course_dept", "")
    year        = state.get("create_course_year", "")
    semester    = state.get("create_course_semester", "")

    if not faculty or not semester:
        state["action"] = None
        set_state(user_id, state)
        bot.send_message(user_id, t(user_id, "main_menu"),
                         reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
        return

    if not course_name or len(course_name) > 50:
        bot.send_message(user_id, "❌ Course name must be 1–50 characters. Please try again:")
        return

    added = add_custom_course(faculty, dept, year, semester, course_name)
    state["action"] = None
    for k in ["create_course_faculty", "create_course_dept",
              "create_course_year", "create_course_semester"]:
        state.pop(k, None)
    set_state(user_id, state)

    fac_key  = _fac_cb_key(faculty)
    dept_key = _dept_cb_key(dept) if dept else ""
    yr_key   = year if year else "direct"
    safe_course = course_name[:20].replace("|", "-")

    if added:
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton(
            t(user_id, "upload_to_course"),
            callback_data=f"upload_crs_{fac_key}|{dept_key}|{yr_key}|{semester}|{safe_course}",
        ))
        markup.add(types.InlineKeyboardButton(
            t(user_id, "back"),
            callback_data=f"browse_s_{fac_key}|{dept_key}|{yr_key}|{semester}",
        ))
        markup.add(types.InlineKeyboardButton(
            t(user_id, "main_menu_btn"), callback_data="main_menu"
        ))
        bot.send_message(
            user_id,
            f"✅ *Course '{course_name}' created!*\n{DIVIDER}\n"
            f"Everyone can now upload and download files from this course.",
            reply_markup=markup, parse_mode="Markdown",
        )
    else:
        bot.send_message(user_id, t(user_id, "course_exists"),
                         reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")


# ── Custom course creation (upload flow) ─────────────────────────────────────

def handle_upload_course_name_input(message) -> None:
    user_id     = message.from_user.id
    course_name = message.text.strip()
    state       = get_state(user_id)
    faculty     = state.get("upload_faculty", "")
    dept        = state.get("upload_dept", "")
    year        = state.get("upload_year", "")
    semester    = state.get("upload_semester", "")

    if not faculty or not semester:
        state["action"] = None
        set_state(user_id, state)
        bot.send_message(user_id, t(user_id, "main_menu"),
                         reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
        return

    if not course_name or len(course_name) > 50:
        bot.send_message(user_id, "❌ Course name must be 1–50 characters. Please try again:")
        return

    added = add_custom_course(faculty, dept, year, semester, course_name)

    if not added:
        bot.send_message(
            user_id,
            f"ℹ️ *Course '{course_name}' already exists.* Proceeding to upload to it.",
            parse_mode="Markdown",
        )

    state["upload_course"] = course_name
    state["action"]        = ACTION_AWAITING_FILE
    set_state(user_id, state)

    dept_display = strip_emoji(dept) if dept else strip_emoji(faculty)
    sem_label    = "Semester 1" if semester == "Sem1" else "Semester 2"
    bot.send_message(
        user_id,
        f"{'✅' if added else '📌'} *Course '{course_name}'*\n"
        f"📍 *{dept_display}* · {year} · {sem_label} · {course_name}\n"
        f"{DIVIDER}\n" + t(user_id, "upload_prompt"),
        reply_markup=types.ReplyKeyboardRemove(),
        parse_mode="Markdown",
    )


# ── Browse callbacks ──────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data.startswith("browse_fac_"))
def cb_browse_faculty(call):
    user_id = call.from_user.id
    fac_key = call.data.replace("browse_fac_", "")
    faculty = find_faculty_by_key(fac_key)
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    state = get_state(user_id)
    state["browse_faculty"] = faculty
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)

    if is_no_semester_faculty(faculty):
        books       = get_books_for(faculty, "", "", "")
        fac_display = strip_emoji(faculty)
        if not books:
            fac_key_nb = _fac_cb_key(faculty)
            m = types.InlineKeyboardMarkup(row_width=1)
            m.add(types.InlineKeyboardButton(
                "📤 Upload to this section",
                callback_data=f"upload_fac_{fac_key_nb}",
            ))
            m.row(
                types.InlineKeyboardButton(t(user_id, "back"), callback_data="browse_bk_fac"),
                types.InlineKeyboardButton(t(user_id, "main_menu_btn"), callback_data="main_menu"),
            )
            bot.send_message(user_id, t(user_id, "no_books"),
                             reply_markup=m, parse_mode="Markdown")
        else:
            bot.send_message(user_id,
                f"📂 *{fac_display}*\n{DIVIDER}\n🗂️ {len(books)} file(s) — tap to download 👇",
                reply_markup=books_keyboard(user_id, books, faculty, "", "", ""),
                parse_mode="Markdown")
        bot.answer_callback_query(call.id)
        return

    if is_special_faculty(faculty):
        depts = FACULTIES.get(faculty, [])
        if not depts:
            bot.send_message(user_id, t(user_id, "select_semester"),
                             reply_markup=semester_keyboard(user_id, faculty, "", ""),
                             parse_mode="Markdown")
            bot.answer_callback_query(call.id)
            return

    bot.send_message(user_id, t(user_id, "select_department"),
                     reply_markup=department_keyboard(user_id, faculty, prefix="browse"),
                     parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("browse_dep_"))
def cb_browse_dept(call):
    user_id  = call.from_user.id
    raw      = call.data.replace("browse_dep_", "")
    parts    = raw.split("|", 1)
    fac_key  = parts[0]
    dept_key = parts[1] if len(parts) > 1 else ""
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(user_id, t(user_id, "select_year"),
                     reply_markup=year_keyboard(user_id, faculty, dept or "", prefix="browse"),
                     parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("browse_yr_"))
def cb_browse_year(call):
    user_id = call.from_user.id
    raw     = call.data.replace("browse_yr_", "")
    parts   = raw.split("|", 2)
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, year = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(user_id, t(user_id, "select_semester"),
                     reply_markup=semester_keyboard(user_id, faculty, dept or "", year, prefix="browse"),
                     parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("browse_s_"))
def cb_browse_semester(call):
    user_id = call.from_user.id
    raw     = call.data.replace("browse_s_", "")
    parts   = raw.split("|", 3)
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, yr_key, semester = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    year = "" if yr_key == "direct" else yr_key
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(user_id, t(user_id, "select_course"),
                     reply_markup=course_listing_keyboard(user_id, faculty, dept or "", year, semester),
                     parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("crs_gen_"))
def cb_course_general(call):
    user_id = call.from_user.id
    parts   = call.data.replace("crs_gen_", "").split("|", 3)
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, yr_key, semester = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    year = "" if yr_key == "direct" else yr_key
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    books        = get_books_for(faculty, dept or "", year, semester, course="__unordered__")
    dept_display = strip_emoji(dept) if dept else strip_emoji(faculty)
    sem_label    = "Semester 1" if semester == "Sem1" else "Semester 2"
    fk = _fac_cb_key(faculty)
    dk = (_dept_cb_key(dept) if dept else "")
    yk = year if year else "direct"
    if not books:
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton(
            "📤 Upload to this section",
            callback_data=f"upload_crs_gen_{fk}|{dk}|{yk}|{semester}",
        ))
        m.row(
            types.InlineKeyboardButton(t(user_id, "back"),
                callback_data=f"browse_s_{fk}|{dk}|{yk}|{semester}"),
            types.InlineKeyboardButton(t(user_id, "main_menu_btn"), callback_data="main_menu"),
        )
        bot.send_message(user_id, t(user_id, "no_books"),
                         reply_markup=m, parse_mode="Markdown")
    else:
        header = (
            f"📂 *{dept_display}*"
            + (f" · {year}" if year else "")
            + f" · {sem_label} · General\n{DIVIDER}\n"
            f"🗂️ {len(books)} file(s) — tap to download 👇"
        )
        bot.send_message(user_id, header,
                         reply_markup=books_keyboard(user_id, books, faculty, dept or "",
                                                     year, semester, course="__unordered__"),
                         parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("crs_c_"))
def cb_course_custom(call):
    user_id = call.from_user.id
    parts   = call.data.replace("crs_c_", "").split("|", 4)
    if len(parts) != 5:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, yr_key, semester, course_name = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    year = "" if yr_key == "direct" else yr_key
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    books        = get_books_for(faculty, dept or "", year, semester, course=course_name)
    dept_display = strip_emoji(dept) if dept else strip_emoji(faculty)
    sem_label    = "Semester 1" if semester == "Sem1" else "Semester 2"
    fk = _fac_cb_key(faculty)
    dk = (_dept_cb_key(dept) if dept else "")
    yk = year if year else "direct"
    safe_course  = course_name[:20].replace("|", "-")
    if not books:
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton(
            "📤 Upload to this course",
            callback_data=f"upload_crs_{fk}|{dk}|{yk}|{semester}|{safe_course}",
        ))
        m.row(
            types.InlineKeyboardButton(t(user_id, "back"),
                callback_data=f"browse_s_{fk}|{dk}|{yk}|{semester}"),
            types.InlineKeyboardButton(t(user_id, "main_menu_btn"), callback_data="main_menu"),
        )
        bot.send_message(user_id,
            f"📭 *{course_name}*\n{DIVIDER}\nNo books here yet.\n💡 Be the first to upload! 🌟",
            reply_markup=m, parse_mode="Markdown")
    else:
        header = (
            f"📂 *{dept_display}*"
            + (f" · {year}" if year else "")
            + f" · {sem_label} · *{course_name}*\n{DIVIDER}\n"
            f"🗂️ {len(books)} file(s) — tap to download 👇"
        )
        bot.send_message(user_id, header,
                         reply_markup=books_keyboard(user_id, books, faculty, dept or "",
                                                     year, semester, course=course_name),
                         parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("crs_create_"))
def cb_course_create(call):
    user_id = call.from_user.id
    parts   = call.data.replace("crs_create_", "").split("|", 3)
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, yr_key, semester = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    year = "" if yr_key == "direct" else yr_key
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    state = get_state(user_id)
    state["action"]               = ACTION_CREATING_COURSE
    state["create_course_faculty"]  = faculty
    state["create_course_dept"]     = dept or ""
    state["create_course_year"]     = year
    state["create_course_semester"] = semester
    set_state(user_id, state)
    bot.send_message(user_id, t(user_id, "create_course_prompt"),
                     reply_markup=types.ReplyKeyboardRemove(), parse_mode="Markdown")
    bot.answer_callback_query(call.id)


# ── Browse back callbacks ─────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data.startswith("browse_bk_"))
def cb_browse_back(call):
    user_id = call.from_user.id
    data    = call.data
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)

    if data == "browse_bk_fac":
        bot.send_message(user_id, t(user_id, "select_faculty"),
                         reply_markup=faculty_keyboard(user_id, prefix="browse"),
                         parse_mode="Markdown")
    elif data.startswith("browse_bk_dep_"):
        faculty = find_faculty_by_key(data.replace("browse_bk_dep_", ""))
        if faculty:
            bot.send_message(user_id, t(user_id, "select_department"),
                             reply_markup=department_keyboard(user_id, faculty, prefix="browse"),
                             parse_mode="Markdown")
    elif data.startswith("browse_bk_yr_"):
        parts = data.replace("browse_bk_yr_", "").split("|", 1)
        if len(parts) == 2:
            faculty, dept = find_faculty_dept_by_key(parts[0], parts[1])
            if faculty:
                bot.send_message(user_id, t(user_id, "select_year"),
                                 reply_markup=year_keyboard(user_id, faculty, dept or "", prefix="browse"),
                                 parse_mode="Markdown")
    elif data.startswith("browse_bk_sem_"):
        parts = data.replace("browse_bk_sem_", "").split("|", 2)
        if len(parts) == 3:
            fac_key, dept_key, yr_key = parts
            faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
            year = "" if yr_key == "direct" else yr_key
            if faculty:
                bot.send_message(user_id, t(user_id, "select_semester"),
                                 reply_markup=semester_keyboard(user_id, faculty, dept or "", year,
                                                                prefix="browse"),
                                 parse_mode="Markdown")
    bot.answer_callback_query(call.id)


# ── Download by file_id ────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data.startswith("dlf_"))
def cb_download_by_file_id(call):
    user_id  = call.from_user.id
    tg_prefix = call.data.replace("dlf_", "")
    db       = load_db()
    book     = next(
        (b for b in db["books"] if b.get("telegram_file_id", "").startswith(tg_prefix)),
        None,
    )
    if not book:
        bot.answer_callback_query(call.id, t(user_id, "file_not_found"))
        return
    bot.answer_callback_query(call.id, "📥 Sending…")
    try:
        name_display = book["file_name"].replace("_", " ").title()[:30]
        voters       = len(book.get("voters", []))
        avg          = round(book.get("stars", 0) / voters) if voters > 0 else 0
        stars_disp   = "⭐" * avg if avg > 0 else "☆ Unrated"
        yr           = book.get("year", "")
        sem          = book.get("semester", "")
        sem_label    = ("Sem 1" if sem == "Sem1" else ("Sem 2" if sem == "Sem2" else ""))
        dept_display = (strip_emoji(book.get("department", ""))
                        or strip_emoji(book.get("faculty", "")))
        caption = (
            f"📄 *{name_display}*\n"
            f"{dept_display}"
            + (f" · {yr}" if yr else "")
            + (f" · {sem_label}" if sem_label else "")
            + f"\n{stars_disp} ({voters} vote{'s' if voters != 1 else ''})"
        )
        bot.send_document(user_id, book["telegram_file_id"],
                          caption=caption, parse_mode="Markdown")

        tg_fid = book.get("telegram_file_id", "")
        bot.send_message(user_id, t(user_id, "download_success"),
                         reply_markup=rating_keyboard(user_id, tg_fid),
                         parse_mode="Markdown")

        if not book.get("course"):
            _send_unordered_tag_prompt(user_id, book)
    except Exception as e:
        logger.error("Send document failed: %s", e)
        bot.send_message(user_id, f"❌ Could not send file. Please try again.",
                         reply_markup=main_menu_keyboard(user_id))


# ── Unordered book tag prompt ──────────────────────────────────────────────────

def _send_unordered_tag_prompt(user_id: int, book: dict | None = None) -> None:
    lang = get_lang(user_id)

    already_has_faculty = bool(book and book.get("faculty"))
    already_has_year    = bool(book and book.get("year"))
    already_has_sem     = bool(book and book.get("semester"))

    if already_has_faculty and already_has_year and already_has_sem:
        faculty  = book["faculty"]
        year     = book["year"]
        semester = book["semester"]
        dept     = book.get("department", "")
        fac_key  = _fac_cb_key(faculty)
        dept_key = _dept_cb_key(dept) if dept else ""
        yr_key   = year if year else "direct"
        predefined, unique_custom = get_all_courses(faculty, dept, year, semester)
        all_courses = predefined + unique_custom
        if not all_courses:
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for course in all_courses[:12]:
            safe = course[:20].replace("|", "-")
            markup.add(types.InlineKeyboardButton(
                f"📘 {course}",
                callback_data=f"tag_crs_{fac_key}|{dept_key}|{yr_key}|{semester}|{safe}",
            ))
        skip_label = "⏭️ Skip" if lang == "en" else "⏭️ ዝለል"
        markup.add(types.InlineKeyboardButton(skip_label, callback_data="main_menu"))
        prompt = (
            "🆘 *Help tag this file!*\n"
            f"{DIVIDER}\n"
            "Which course does this file belong to?"
            if lang == "en" else
            "🆘 *ፋይሉን ለምድብ ይርዱ!*\n"
            f"{DIVIDER}\n"
            "ይህ ፋይል ለየትኛው ኮርስ ነው?"
        )
        bot.send_message(user_id, prompt, reply_markup=markup, parse_mode="Markdown")
        return

    if lang == "am":
        msg = (
            "🆘 *ቦቱን ይርዱ!*\n"
            f"{DIVIDER}\n"
            "ይህ ፋይል ያልተደራጀ ነው። ለየትኛው ፋካልቲ ነው?\n"
            "ፋካልቲ ይምረጡ ወይም ዝለሉ።"
        )
    else:
        msg = (
            "🆘 *Help the Bot Tag This File!*\n"
            f"{DIVIDER}\n"
            "This file has no course yet. Which faculty does it belong to?\n"
            "Select a faculty to tag it, or skip."
        )
    markup = types.InlineKeyboardMarkup(row_width=1)
    seen_keys: set[str] = set()
    for faculty in FACULTIES:
        key = _fac_cb_key(faculty)
        if key in seen_keys:
            key = key[:20] + str(len(seen_keys))
        seen_keys.add(key)
        markup.add(types.InlineKeyboardButton(
            faculty, callback_data=f"untag_fac_{key}"
        ))
    skip_label = "⏭️ Skip" if lang == "en" else "⏭️ ዝለል"
    markup.add(types.InlineKeyboardButton(skip_label, callback_data="main_menu"))
    bot.send_message(user_id, msg, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith("untag_fac_"))
def cb_untag_faculty(call):
    user_id = call.from_user.id
    fac_key = call.data.replace("untag_fac_", "")
    faculty = find_faculty_by_key(fac_key)
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    lang = get_lang(user_id)
    bot.answer_callback_query(call.id)

    depts = FACULTIES.get(faculty, [])
    if not depts or is_special_faculty(faculty):
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.row(
            types.InlineKeyboardButton("📙 Semester 1", callback_data=f"untag_sem_{fac_key}||direct|Sem1"),
            types.InlineKeyboardButton("📗 Semester 2", callback_data=f"untag_sem_{fac_key}||direct|Sem2"),
        )
        skip_label = "⏭️ Skip" if lang == "en" else "⏭️ ዝለል"
        markup.add(types.InlineKeyboardButton(skip_label, callback_data="main_menu"))
        prompt = "📅 *Select Semester:*" if lang == "en" else "📅 *ሴሜስተር ይምረጡ:*"
        bot.send_message(user_id, prompt, reply_markup=markup, parse_mode="Markdown")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for dept in depts:
        dept_key = _dept_cb_key(dept)
        markup.add(types.InlineKeyboardButton(
            dept, callback_data=f"untag_dep_{fac_key}|{dept_key}"
        ))
    skip_label = "⏭️ Skip" if lang == "en" else "⏭️ ዝለል"
    markup.add(types.InlineKeyboardButton(skip_label, callback_data="main_menu"))
    prompt = "📂 *Select Department:*" if lang == "en" else "📂 *ዲፓርትመንት ይምረጡ:*"
    bot.send_message(user_id, prompt, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith("untag_dep_"))
def cb_untag_dept(call):
    user_id  = call.from_user.id
    raw      = call.data.replace("untag_dep_", "")
    parts    = raw.split("|", 1)
    fac_key  = parts[0]
    dept_key = parts[1] if len(parts) > 1 else ""
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    lang = get_lang(user_id)
    bot.answer_callback_query(call.id)

    num_years = get_dept_year_count(dept or "")
    markup = types.InlineKeyboardMarkup(row_width=3)
    for i in range(num_years):
        markup.add(types.InlineKeyboardButton(
            YEARS[i], callback_data=f"untag_yr_{fac_key}|{dept_key}|{YEAR_LABELS[i]}"
        ))
    skip_label = "⏭️ Skip" if lang == "en" else "⏭️ ዝለል"
    markup.add(types.InlineKeyboardButton(skip_label, callback_data="main_menu"))
    prompt = "📅 *Select Year:*" if lang == "en" else "📅 *ዓመት ይምረጡ:*"
    bot.send_message(user_id, prompt, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith("untag_yr_"))
def cb_untag_year(call):
    user_id = call.from_user.id
    raw     = call.data.replace("untag_yr_", "")
    parts   = raw.split("|", 2)
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, yr = parts
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    lang = get_lang(user_id)
    bot.answer_callback_query(call.id)

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton("📙 Semester 1", callback_data=f"untag_sem_{fac_key}|{dept_key}|{yr}|Sem1"),
        types.InlineKeyboardButton("📗 Semester 2", callback_data=f"untag_sem_{fac_key}|{dept_key}|{yr}|Sem2"),
    )
    skip_label = "⏭️ Skip" if lang == "en" else "⏭️ ዝለል"
    markup.add(types.InlineKeyboardButton(skip_label, callback_data="main_menu"))
    prompt = "📅 *Select Semester:*" if lang == "en" else "📅 *ሴሜስተር ይምረጡ:*"
    bot.send_message(user_id, prompt, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith("untag_sem_"))
def cb_untag_semester(call):
    user_id = call.from_user.id
    raw     = call.data.replace("untag_sem_", "")
    parts   = raw.split("|", 3)
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, yr_key, semester = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    year = "" if yr_key == "direct" else yr_key
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    lang = get_lang(user_id)
    bot.answer_callback_query(call.id)

    if not faculty:
        msg = "✅ *Thank you for helping!* 🌟" if lang == "en" else "✅ *አመሰግናለሁ!* 🌟"
        bot.send_message(user_id, msg, reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
        return

    predefined, unique_custom = get_all_courses(faculty, dept or "", year, semester)
    all_courses = predefined + unique_custom
    if not all_courses:
        msg = "✅ *Tagged!* Thank you! 🌟" if lang == "en" else "✅ *ተለጥፏል!* አመሰግናለሁ! 🌟"
        bot.send_message(user_id, msg, reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for course in all_courses[:12]:
        safe = course[:20].replace("|", "-")
        markup.add(types.InlineKeyboardButton(
            f"📘 {course}",
            callback_data=f"tag_crs_{fac_key}|{dept_key}|{yr_key}|{semester}|{safe}",
        ))
    skip_label = "⏭️ Skip" if lang == "en" else "⏭️ ዝለል"
    markup.add(types.InlineKeyboardButton(skip_label, callback_data="main_menu"))
    prompt = (
        "📚 *Which course does this file belong to?*"
        if lang == "en" else
        "📚 *ፋይሉ ለየትኛው ኮርስ ነው?*"
    )
    bot.send_message(user_id, prompt, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith("tag_crs_"))
def cb_tag_course(call):
    user_id = call.from_user.id
    raw     = call.data.replace("tag_crs_", "")
    parts   = raw.split("|", 4)
    if len(parts) != 5:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, yr_key, semester, safe_course = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    year = "" if yr_key == "direct" else yr_key
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    lang = get_lang(user_id)
    bot.answer_callback_query(call.id)

    if not faculty:
        msg = "✅ *Thank you for helping!* 🌟" if lang == "en" else "✅ *አመሰግናለሁ!* 🌟"
        bot.send_message(user_id, msg, reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
        return

    msg = (
        f"✅ *Tagged as '{safe_course}'!* Thank you for helping organise the library! 🌟"
        if lang == "en" else
        f"✅ *'{safe_course}' ብሎ ተለጥፏል!* ቤተ-መጻሕፍቱን ለማዘጋጀት ስለ ርዳታዎ አመሰግናለሁ! 🌟"
    )
    bot.send_message(user_id, msg, reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")


# ── Help-the-bot prompt (legacy) ────────────────────────────────────────────

def _send_help_bot_prompt(user_id: int, fac_key: str, dept_key: str,
                          yr_key: str, semester: str) -> None:
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    if not faculty:
        return
    year   = "" if yr_key == "direct" else yr_key
    markup = types.InlineKeyboardMarkup(row_width=1)
    predefined, unique_custom = get_all_courses(faculty, dept or "", year, semester)
    all_courses = predefined + unique_custom
    for course in all_courses[:12]:
        safe = course[:20].replace("|", "-")
        markup.add(types.InlineKeyboardButton(
            f"📘 {course}",
            callback_data=f"hbtag_{fac_key}|{dept_key}|{yr_key}|{semester}|{safe}",
        ))
    markup.add(types.InlineKeyboardButton(t(user_id, "help_bot_skip"),
                                          callback_data="main_menu"))
    bot.send_message(user_id, t(user_id, "help_bot_prompt"),
                     reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith("hbtag_"))
def cb_help_bot_tag(call):
    user_id = call.from_user.id
    parts   = call.data.replace("hbtag_", "").split("|", 4)
    if len(parts) != 5:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)
    bot.send_message(user_id, t(user_id, "help_bot_tagged"),
                     reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")


# ── Rating callback ───────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data.startswith("rt_"))
def cb_rating(call):
    user_id = call.from_user.id
    raw   = call.data[len("rt_"):]
    parts = raw.split("_", 1)
    if len(parts) != 2:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    try:
        stars_given = int(parts[0])
    except ValueError:
        bot.answer_callback_query(call.id, "Invalid rating.")
        return
    if not 1 <= stars_given <= 5:
        bot.answer_callback_query(call.id, "Invalid rating value.")
        return

    tg_prefix = parts[1]
    db        = load_db()
    book      = next(
        (b for b in db["books"] if b.get("telegram_file_id", "").startswith(tg_prefix)),
        None,
    )
    if not book:
        bot.answer_callback_query(call.id, t(user_id, "file_not_found"), show_alert=True)
        return

    uid = str(user_id)
    if uid in book.get("voters", []):
        bot.answer_callback_query(call.id, t(user_id, "already_voted"), show_alert=True)
        return

    book.setdefault("voters", []).append(uid)
    book["stars"] = book.get("stars", 0) + stars_given

    uploader_id = str(book.get("uploader_id", ""))
    if uploader_id and uploader_id in db["users"]:
        db["users"][uploader_id]["stars_received"] = (
            db["users"][uploader_id].get("stars_received", 0) + stars_given
        )
    save_db(db)
    bot.answer_callback_query(call.id, t(user_id, "vote_recorded"), show_alert=True)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(user_id, t(user_id, "vote_recorded"),
                     reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")


# ── Upload flow callbacks ─────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_fac_"))
def cb_upload_faculty(call):
    user_id = call.from_user.id
    fac_key = call.data.replace("upload_fac_", "")
    faculty = find_faculty_by_key(fac_key)
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)

    if is_no_semester_faculty(faculty):
        state = get_state(user_id)
        state.update({
            "upload_faculty":  faculty,
            "upload_dept":     "",
            "upload_year":     "",
            "upload_semester": "",
            "upload_course":   None,
            "action":          ACTION_AWAITING_FILE,
        })
        set_state(user_id, state)
        fac_display = strip_emoji(faculty)
        bot.send_message(user_id,
            f"📍 *{fac_display}*\n{DIVIDER}\n" + t(user_id, "upload_prompt"),
            reply_markup=types.ReplyKeyboardRemove(), parse_mode="Markdown")
        bot.answer_callback_query(call.id)
        return

    if is_special_faculty(faculty):
        depts = FACULTIES.get(faculty, [])
        if not depts:
            bot.send_message(user_id, t(user_id, "select_semester"),
                             reply_markup=semester_keyboard(user_id, faculty, "", "", prefix="upload"),
                             parse_mode="Markdown")
            bot.answer_callback_query(call.id)
            return

    bot.send_message(user_id, t(user_id, "select_department"),
                     reply_markup=department_keyboard(user_id, faculty, prefix="upload"),
                     parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_dep_"))
def cb_upload_dept(call):
    user_id  = call.from_user.id
    raw      = call.data.replace("upload_dep_", "")
    parts    = raw.split("|", 1)
    fac_key  = parts[0]
    dept_key = parts[1] if len(parts) > 1 else ""
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(user_id, t(user_id, "select_year"),
                     reply_markup=year_keyboard(user_id, faculty, dept or "", prefix="upload"),
                     parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_yr_"))
def cb_upload_year(call):
    user_id = call.from_user.id
    raw     = call.data.replace("upload_yr_", "")
    parts   = raw.split("|", 2)
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, year = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(user_id, t(user_id, "select_semester"),
                     reply_markup=semester_keyboard(user_id, faculty, dept or "", year, prefix="upload"),
                     parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_s_"))
def cb_upload_semester(call):
    user_id = call.from_user.id
    raw     = call.data.replace("upload_s_", "")
    parts   = raw.split("|", 3)
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, yr_key, semester = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    year = "" if yr_key == "direct" else yr_key
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(user_id, t(user_id, "course_select_upload_prompt"),
                     reply_markup=upload_course_keyboard(user_id, faculty, dept or "", year, semester),
                     parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_crs_gen_"))
def cb_upload_course_gen(call):
    user_id = call.from_user.id
    parts   = call.data.replace("upload_crs_gen_", "").split("|", 3)
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, yr_key, semester = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    year = "" if yr_key == "direct" else yr_key
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    state = get_state(user_id)
    state.update({
        "upload_faculty":  faculty,
        "upload_dept":     dept or "",
        "upload_year":     year,
        "upload_semester": semester,
        "upload_course":   None,
        "action":          ACTION_AWAITING_FILE,
    })
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    dept_display = strip_emoji(dept) if dept else strip_emoji(faculty)
    sem_label    = "Semester 1" if semester == "Sem1" else "Semester 2"
    loc = f"*{dept_display}*" + (f" · {year}" if year else "") + f" · {sem_label} · General"
    bot.send_message(user_id,
        f"📍 {loc}\n{DIVIDER}\n" + t(user_id, "upload_prompt"),
        reply_markup=types.ReplyKeyboardRemove(), parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(
    func=lambda call: (
        call.data.startswith("upload_crs_")
        and not call.data.startswith("upload_crs_gen_")
        and not call.data.startswith("upload_crs_create_")
    )
)
def cb_upload_course_select(call):
    user_id = call.from_user.id
    parts   = call.data.replace("upload_crs_", "").split("|", 4)
    if len(parts) != 5:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, yr_key, semester, course_name = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    year = "" if yr_key == "direct" else yr_key
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    state = get_state(user_id)
    state.update({
        "upload_faculty":  faculty,
        "upload_dept":     dept or "",
        "upload_year":     year,
        "upload_semester": semester,
        "upload_course":   course_name,
        "action":          ACTION_AWAITING_FILE,
    })
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    dept_display = strip_emoji(dept) if dept else strip_emoji(faculty)
    sem_label    = "Semester 1" if semester == "Sem1" else "Semester 2"
    loc = f"*{dept_display}*" + (f" · {year}" if year else "") + f" · {sem_label} · *{course_name}*"
    bot.send_message(user_id,
        f"📍 {loc}\n{DIVIDER}\n" + t(user_id, "upload_prompt"),
        reply_markup=types.ReplyKeyboardRemove(), parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_crs_create_"))
def cb_upload_course_create(call):
    user_id = call.from_user.id
    parts   = call.data.replace("upload_crs_create_", "").split("|", 3)
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, yr_key, semester = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    year = "" if yr_key == "direct" else yr_key
    if not faculty:
        bot.answer_callback_query(call.id, "Faculty not found.")
        return
    state = get_state(user_id)
    state.update({
        "upload_faculty":  faculty,
        "upload_dept":     dept or "",
        "upload_year":     year,
        "upload_semester": semester,
        "action":          ACTION_CREATING_UPLOAD_CRS,
    })
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(user_id, t(user_id, "create_course_prompt"),
                     reply_markup=types.ReplyKeyboardRemove(), parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_bk_"))
def cb_upload_back(call):
    user_id = call.from_user.id
    data    = call.data
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    if data == "upload_bk_fac":
        bot.send_message(user_id, t(user_id, "select_faculty"),
                         reply_markup=faculty_keyboard(user_id, prefix="upload"),
                         parse_mode="Markdown")
    elif data.startswith("upload_bk_dep_"):
        faculty = find_faculty_by_key(data.replace("upload_bk_dep_", ""))
        if faculty:
            bot.send_message(user_id, t(user_id, "select_department"),
                             reply_markup=department_keyboard(user_id, faculty, prefix="upload"),
                             parse_mode="Markdown")
    elif data.startswith("upload_bk_yr_"):
        parts = data.replace("upload_bk_yr_", "").split("|", 1)
        if len(parts) == 2:
            faculty, dept = find_faculty_dept_by_key(parts[0], parts[1])
            if faculty:
                bot.send_message(user_id, t(user_id, "select_year"),
                                 reply_markup=year_keyboard(user_id, faculty, dept or "", prefix="upload"),
                                 parse_mode="Markdown")
    elif data.startswith("upload_bk_sem_"):
        parts = data.replace("upload_bk_sem_", "").split("|", 2)
        if len(parts) == 3:
            fac_key, dept_key, yr_key = parts
            faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
            year = "" if yr_key == "direct" else yr_key
            if faculty:
                bot.send_message(user_id, t(user_id, "select_semester"),
                                 reply_markup=semester_keyboard(user_id, faculty, dept or "", year,
                                                                prefix="upload"),
                                 parse_mode="Markdown")
    bot.answer_callback_query(call.id)


# ── Admin callbacks ───────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def cb_admin(call):
    user_id = call.from_user.id
    if user_id != OWNER_ID:
        bot.answer_callback_query(call.id, t(user_id, "not_admin"))
        return
    data = call.data
    db   = load_db()

    if data == "admin_list_books":
        books = db["books"]
        if not books:
            bot.send_message(user_id, "📭 No books in the database.")
        else:
            lines = [
                f"📄 `{b['file_name']}`\n"
                f"   {strip_emoji(b.get('faculty','?'))} · "
                f"{strip_emoji(b.get('department',''))} · "
                f"{b.get('year','')} · {b.get('semester','')} · "
                f"Course: {b.get('course','—')}"
                for b in books
            ]
            text = f"📚 *Books ({len(books)})*\n{DIVIDER}\n" + "\n\n".join(lines)
            for i in range(0, len(text), 4000):
                bot.send_message(user_id, text[i: i + 4000], parse_mode="Markdown")

    elif data == "admin_list_users":
        users = db["users"]
        if not users:
            bot.send_message(user_id, "👥 No users yet.")
        else:
            lines = [
                f"👤 *{info.get('name', uid)}*  `{uid}`\n"
                f"   📚{info.get('uploaded_books', 0)} ⭐{info.get('stars_received', 0)}\n"
                f"   🏫 {info.get('faculty','?')} · {info.get('department','?')} · {info.get('year','?')}"
                for uid, info in users.items()
            ]
            text = f"👥 *Users ({len(users)})*\n{DIVIDER}\n" + "\n\n".join(lines)
            for i in range(0, len(text), 4000):
                bot.send_message(user_id, text[i: i + 4000], parse_mode="Markdown")

    elif data == "admin_delete_prompt":
        state = get_state(user_id)
        state["action"] = ACTION_ADMIN_DELETE
        set_state(user_id, state)
        bot.send_message(user_id,
            f"🗑️ *Delete Book*\n{DIVIDER}\n"
            f"Send the *exact* file name (as stored — use Books list to find it):",
            parse_mode="Markdown")

    elif data == "admin_delete_course_prompt":
        state = get_state(user_id)
        state["action"] = ACTION_ADMIN_DELETE_COURSE
        set_state(user_id, state)
        custom_courses = db.get("custom_courses", {})
        if custom_courses:
            lines = []
            for loc_key, courses in custom_courses.items():
                for cname in courses:
                    lines.append(f"• `{loc_key}|{cname}`")
            bot.send_message(user_id,
                "📂 *Custom Courses*\n" + DIVIDER + "\n" + "\n".join(lines[:30]),
                parse_mode="Markdown")
        else:
            bot.send_message(user_id, "📭 No custom courses exist yet.")
        bot.send_message(user_id,
            f"🗑️ *Delete Course*\n{DIVIDER}\n"
            f"Format:\n`FacultyKey|DeptKey|Year|Semester|CourseName`\n\n"
            f"Example:\n`Engineering|Software Engineering|Year2|Sem1|Calculus I`\n\n"
            f"⚠️ This will also delete ALL files in that course!",
            parse_mode="Markdown")

    elif data == "admin_broadcast_prompt":
        state = get_state(user_id)
        state["action"] = ACTION_ADMIN_BROADCAST
        set_state(user_id, state)
        total = len(db.get("users", {}))
        bot.send_message(user_id,
            f"📢 *Broadcast Message*\n{DIVIDER}\n"
            f"Will be sent to all *{total}* users.\n\nType your announcement:",
            parse_mode="Markdown")

    elif data == "admin_dm_prompt":
        state = get_state(user_id)
        state["action"] = ACTION_ADMIN_DM_TARGET
        set_state(user_id, state)
        bot.send_message(user_id,
            f"✉️ *Direct Message*\n{DIVIDER}\n"
            f"Send the *User ID* of the target user:",
            parse_mode="Markdown")

    elif data == "admin_ai_disable":
        set_ai_enabled(False)
        db2 = load_db()
        save_db(db2)
        bot.send_message(user_id,
            f"🔴 *AI disabled.*\n"
            f"Users will see the 'Coming Soon' message.",
            reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")

    elif data == "admin_ai_enable":
        set_ai_enabled(True)
        db2 = load_db()
        save_db(db2)
        bot.send_message(user_id,
            f"🟢 *AI enabled.*\n"
            f"Users can use mtu.ai normally.",
            reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")

    bot.answer_callback_query(call.id)


# ── Document upload handler ────────────────────────────────────────────────────

def _process_document(message) -> None:
    user_id = message.from_user.id
    state   = get_state(user_id)

    if state.get("action") != ACTION_AWAITING_FILE:
        bot.send_message(user_id, t(user_id, "main_menu"),
                         reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
        return

    faculty  = state.get("upload_faculty", "")
    dept     = state.get("upload_dept", "")
    year     = state.get("upload_year", "")
    semester = state.get("upload_semester", "")
    course   = state.get("upload_course", None)

    if not faculty or not semester:
        bot.send_message(user_id, t(user_id, "upload_select_location"),
                         reply_markup=faculty_keyboard(user_id, prefix="upload"),
                         parse_mode="Markdown")
        return

    doc       = message.document
    file_name = doc.file_name or "unknown"
    ext       = os.path.splitext(file_name)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        bot.send_message(user_id, t(user_id, "upload_invalid_type"),
                         reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
        return

    if doc.file_size and doc.file_size > MAX_FILE_SIZE:
        bot.send_message(user_id, t(user_id, "upload_too_large"),
                         reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
        return

    clean_name = clean_filename(file_name)
    db         = load_db()

    fac_clean     = strip_emoji(faculty)
    dept_clean    = strip_emoji(dept) if dept else ""
    year_save     = year
    semester_save = semester
    course_save   = course if course else None

    for b in db["books"]:
        if (b["file_name"] == clean_name
                and strip_emoji(b.get("faculty", "")) == fac_clean
                and strip_emoji(b.get("department", "")) == dept_clean
                and b.get("year", "") == year_save
                and b.get("semester", "") == semester_save
                and (b.get("course") or None) == (course_save or None)):
            bot.send_message(user_id, t(user_id, "upload_duplicate"),
                             reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
            return

    uploading_msg = bot.send_message(user_id, t(user_id, "uploading"), parse_mode="Markdown")

    user_info = get_user_info(db, user_id)
    fname     = message.from_user.first_name or ""
    lname     = message.from_user.last_name  or ""
    user_info["name"]           = (fname + " " + lname).strip() or str(user_id)
    user_info["uploaded_books"] = user_info.get("uploaded_books", 0) + 1

    new_book: dict = {
        "file_name":       clean_name,
        "faculty":         fac_clean,
        "department":      dept_clean,
        "year":            year_save,
        "semester":        semester_save,
        "uploader_id":     str(user_id),
        "telegram_file_id": doc.file_id,
        "stars":           0,
        "voters":          [],
    }
    if course_save:
        new_book["course"] = course_save

    db["books"].append(new_book)

    try:
        save_db(db)
        try:
            bot.delete_message(user_id, uploading_msg.message_id)
        except Exception:
            pass

        sem_disp  = ("Sem 1" if semester_save == "Sem1" else
                     "Sem 2" if semester_save == "Sem2" else "")
        loc_parts = [p for p in [fac_clean, dept_clean, year_save, sem_disp] if p]
        if course_save:
            loc_parts.append(course_save)
        else:
            loc_parts.append("General")
        loc_str = " › ".join(loc_parts) if loc_parts else "General"

        state["action"] = ACTION_AWAITING_FILE
        set_state(user_id, state)

        done_markup = types.InlineKeyboardMarkup(row_width=1)
        done_markup.add(
            types.InlineKeyboardButton("✅ Done — Main Menu", callback_data="main_menu")
        )
        bot.send_message(
            user_id,
            f"{t(user_id, 'upload_success')}\n📍 *{loc_str}*\n\n"
            f"📎 _Send the next file or tap Done when finished._",
            reply_markup=done_markup, parse_mode="Markdown",
        )

        if fac_clean and dept_clean:
            threading.Thread(
                target=_notify_department_users,
                args=(user_id, fac_clean, dept_clean, year_save, semester_save, clean_name),
                daemon=True,
            ).start()

    except Exception as e:
        logger.error("Save after upload failed: %s", e)
        try:
            bot.delete_message(user_id, uploading_msg.message_id)
        except Exception:
            pass
        bot.send_message(user_id, t(user_id, "upload_error"),
                         reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")


@bot.message_handler(content_types=["document"])
def handle_document(message):
    threading.Thread(target=_process_document, args=(message,), daemon=True).start()


# ── DB channel post handler ────────────────────────────────────────────────────

@bot.channel_post_handler(content_types=["document"])
def handle_channel_db_upload(post):
    global _db_cache, _states_cache, _ai_enabled
    if not DB_CHANNEL_ID:
        return
    if getattr(post.chat, "id", None) != DB_CHANNEL_ID:
        return
    doc   = getattr(post, "document", None)
    fname = (getattr(doc, "file_name", "") or "") if doc else ""

    if fname == "database.json":
        logger.info("database.json posted to DB channel (msg=%s) — loading…", post.message_id)
        result = _download_from_channel(doc.file_id)
        if result is None or not isinstance(result.get("books"), list):
            logger.warning("database.json from channel post is invalid — ignoring")
            return
        with _db_lock:
            current = _db_cache
        merged = _merge_db(current, result)
        with _db_lock:
            _db_cache = merged
        if "ai_enabled" in merged:
            with _ai_enabled_lock:
                _ai_enabled = bool(merged["ai_enabled"])
        DB_MSG_IDS["db_msg"]  = post.message_id
        DB_MSG_IDS["db_file"] = doc.file_id
        logger.info("database.json loaded from channel post ✅ (%d books)", len(merged.get("books", [])))
        _db_executor.submit(_bg_save_db, merged)

    elif fname == "user_choices.json":
        logger.info("user_choices.json posted to DB channel (msg=%s) — loading…", post.message_id)
        result = _download_from_channel(doc.file_id)
        if result is None or not isinstance(result, dict):
            logger.warning("user_choices.json from channel post is invalid — ignoring")
            return
        with _states_lock:
            _states_cache = result
        DB_MSG_IDS["states_msg"]  = post.message_id
        DB_MSG_IDS["states_file"] = doc.file_id
        logger.info("user_choices.json loaded from channel post ✅ (%d users)", len(result))
        _states_executor.submit(_bg_save_states, result)


# ── Main text handler (must be last) ──────────────────────────────────────────

@bot.message_handler(func=lambda msg: True, content_types=["text"])
def handle_text(message):
    user_id = message.from_user.id
    text    = message.text.strip()
    state   = get_state(user_id)

    if user_id == OWNER_ID:
        if state.get("action") == ACTION_ADMIN_REPLY:
            with pending_reply_lock:
                target = pending_reply_targets.get(OWNER_ID)
            if target:
                send_owner_reply(message, target)
                return
        if state.get("action") == ACTION_ADMIN_BROADCAST:
            do_broadcast(message)
            return
        if state.get("action") == ACTION_ADMIN_DM_TARGET:
            handle_admin_dm_target(message)
            return
        if state.get("action") == ACTION_ADMIN_DM_MESSAGE:
            handle_admin_dm_message(message)
            return

    if state.get("action") == ACTION_AI_CHAT:
        if text == t(user_id, "exit_chat"):
            with ai_histories_lock:
                ai_chat_histories.pop(user_id, None)
            state["action"] = None
            set_state(user_id, state)
            bot.send_message(
                user_id,
                ("👋 *Chat ended.* See you next time!\n\n" if get_lang(user_id) == "en"
                 else "👋 *ውይይት ተጠናቀቀ።* በቅርቡ!\n\n")
                + t(user_id, "main_menu"),
                reply_markup=main_menu_keyboard(user_id),
                parse_mode="Markdown",
            )
        else:
            handle_ai_message(message)
        return

    action = state.get("action")
    if action == ACTION_CONTACT:
        send_contact_message(message)
        return
    if action == ACTION_SEARCH:
        handle_search(message)
        return
    if action == ACTION_ADMIN_DELETE:
        handle_admin_delete(message)
        return
    if action == ACTION_ADMIN_DELETE_COURSE:
        handle_admin_delete_course_input(message)
        return
    if action == ACTION_CREATING_COURSE:
        handle_course_name_input(message)
        return
    if action == ACTION_CREATING_UPLOAD_CRS:
        handle_upload_course_name_input(message)
        return

    if text == t(user_id, "browse"):
        state["action"] = "browse"
        set_state(user_id, state)
        bot.send_message(user_id, t(user_id, "select_faculty"),
                         reply_markup=faculty_keyboard(user_id, prefix="browse"),
                         parse_mode="Markdown")

    elif text == t(user_id, "upload"):
        state["action"] = "upload"
        set_state(user_id, state)
        bot.send_message(user_id, t(user_id, "upload_select_location"),
                         reply_markup=faculty_keyboard(user_id, prefix="upload"),
                         parse_mode="Markdown")

    elif text == t(user_id, "leaderboard"):
        show_leaderboard(user_id)

    elif text == t(user_id, "help"):
        show_help(user_id)

    elif text == t(user_id, "contact"):
        state["action"] = ACTION_CONTACT
        set_state(user_id, state)
        bot.send_message(user_id, t(user_id, "contact_prompt"), parse_mode="Markdown")

    elif text == t(user_id, "mtu_ai"):
        if not is_ai_enabled():
            lang = get_lang(user_id)
            msg  = MTU_AI_COMING_SOON_EN if lang == "en" else MTU_AI_COMING_SOON_AM
            bot.send_message(user_id, msg, parse_mode="Markdown")
            return
        with ai_histories_lock:
            ai_chat_histories.pop(user_id, None)
        state["action"] = ACTION_AI_CHAT
        set_state(user_id, state)
        welcome = MTU_WELCOME_EN if get_lang(user_id) == "en" else MTU_WELCOME_AM
        bot.send_message(user_id, welcome,
                         reply_markup=ai_keyboard(user_id), parse_mode="Markdown")

    elif text == t(user_id, "search"):
        state["action"] = ACTION_SEARCH
        set_state(user_id, state)
        bot.send_message(user_id, t(user_id, "search_prompt"), parse_mode="Markdown")

    elif text == t(user_id, "request_file"):
        bot.send_message(
            user_id,
            f"🆘 *Request a File*\n{DIVIDER}\n"
            f"Can't find what you need? Join our group and post a request!\n\n"
            f"👥 [Join the Group]({GROUP_LINK})",
            reply_markup=main_menu_keyboard(user_id),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )

    else:
        bot.send_message(user_id, t(user_id, "main_menu"),
                         reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")


# ── Flask keep-alive ──────────────────────────────────────────────────────────

flask_app = Flask(__name__)


@flask_app.route("/")
def index():
    return "Bot is running ✅"


def run_flask() -> None:
    port = int(os.environ.get("PORT", 8080))
    try:
        flask_app.run(host="0.0.0.0", port=port)
    except OSError as e:
        logger.warning("Flask failed to start on port %d: %s", port, e)


# ── Signal handling ───────────────────────────────────────────────────────────

def graceful_shutdown(signum, frame):
    logger.info("Graceful shutdown requested (signal %s)…", signum)
    sys.exit(0)


signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT,  graceful_shutdown)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    global _db_cache, _ai_enabled

    logger.info("Starting MTU Bot v3.0…")

    if DB_CHANNEL_ID:
        logger.info("Loading DB from channel %d…", DB_CHANNEL_ID)
        _load_index()
    else:
        logger.warning("DB_CHANNEL_ID not set — loading from local file only")
        local_db = _load_local_db()
        if local_db:
            with _db_lock:
                _db_cache = local_db
            if "ai_enabled" in local_db:
                with _ai_enabled_lock:
                    _ai_enabled = bool(local_db["ai_enabled"])
            logger.info("Running with local DB only (%d books)",
                        len(local_db.get("books", [])))
        else:
            logger.warning("No local database.json found — starting with empty DB")

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    logger.info("Bot polling started.")
    bot.infinity_polling(
        timeout=60,
        long_polling_timeout=60,
        skip_pending=True,
        allowed_updates=[
            "message", "edited_message",
            "channel_post", "edited_channel_post",
            "callback_query", "inline_query",
        ],
    )


if __name__ == "__main__":
    main()
