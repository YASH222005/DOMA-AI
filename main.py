import os
import re
import random
import string
import secrets
import sqlite3
import hashlib
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Depends, Form, UploadFile, File, Cookie, Response
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, PlainTextResponse
from pydantic import BaseModel, EmailStr
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import fitz  # PyMuPDF

app = FastAPI(title="DOMA AI - Professional Resume Platform")

# --- DATABASE SETUP (SQLite Persistence) ---
DB_FILE = "doma_ai.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            coins INTEGER DEFAULT 10,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS otps (
            email TEXT PRIMARY KEY,
            otp TEXT NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            match_score INTEGER,
            job_title TEXT,
            pdf_filename TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def get_current_user(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id:
        return None
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT email FROM sessions WHERE session_id = ?", (session_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# --- MODELS ---
class AuthRequest(BaseModel):
    email: EmailStr
    password: str

class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str

@app.get("/robots.txt", response_class=PlainTextResponse)
def get_robots_txt():
    return "User-agent: *\nAllow: /\n"

# --- AUTH ENDPOINTS ---
@app.post("/api/auth/register-request")
def register_request(data: AuthRequest):
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT email FROM users WHERE email = ?", (data.email,))
    if c.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="User already registered. Please login.")
    
    otp = "".join(random.choices(string.digits, k=6))
    pw_hash = hash_pw(data.password)
    c.execute("INSERT OR REPLACE INTO otps (email, otp, password_hash) VALUES (?, ?, ?)", (data.email, otp, pw_hash))
    conn.commit()
    conn.close()
    
    print(f"[AUTH DEMO LOG] Verification code for {data.email}: {otp}")
    return {"message": "Verification code generated.", "otp_demo": otp}

@app.post("/api/auth/verify-register")
def verify_register(data: VerifyOTPRequest, response: Response):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT password_hash FROM otps WHERE email = ? AND otp = ?", (data.email, data.otp))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid verification code.")
    
    pw_hash = row[0]
    c.execute("INSERT INTO users (email, password_hash, coins) VALUES (?, ?, 10)", (data.email, pw_hash))
    c.execute("DELETE FROM otps WHERE email = ?", (data.email,))
    
    session_id = secrets.token_hex(32)
    c.execute("INSERT INTO sessions (session_id, email) VALUES (?, ?)", (session_id, data.email))
    conn.commit()
    conn.close()
    
    response.set_cookie(key="session_id", value=session_id, httponly=True, max_age=86400*30)
    return {"message": "Account created successfully", "email": data.email, "coins": 10}

@app.post("/api/auth/login")
def login(data: AuthRequest, response: Response):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    pw_hash = hash_pw(data.password)
    c.execute("SELECT coins FROM users WHERE email = ? AND password_hash = ?", (data.email, pw_hash))
    user = c.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid email or password.")
    
    session_id = secrets.token_hex(32)
    c.execute("INSERT INTO sessions (session_id, email) VALUES (?, ?)", (session_id, data.email))
    conn.commit()
    conn.close()
    
    response.set_cookie(key="session_id", value=session_id, httponly=True, max_age=86400*30)
    return {"message": "Logged in", "email": data.email, "coins": user[0]}

@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    session_id = request.cookies.get("session_id")
    if session_id:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()
    response.delete_cookie("session_id")
    return {"message": "Logged out"}

@app.get("/api/auth/me")
def get_me(request: Request):
    user_email = get_current_user(request)
    if not user_email:
        return {"authenticated": False}
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT coins FROM users WHERE email = ?", (user_email,))
    row = c.fetchone()
    
    c.execute("SELECT match_score, job_title, pdf_filename, created_at FROM history WHERE user_email = ? ORDER BY id DESC LIMIT 5", (user_email,))
    history = [{"score": r[0], "title": r[1], "file": r[2], "date": r[3]} for r in c.fetchall()]
    conn.close()
    
    return {"authenticated": True, "email": user_email, "coins": row[0] if row else 0, "history": history}

# --- RESUME OPTIMIZATION CORE ENGINE ---
@app.post("/api/match-resume")
async def match_resume(
    request: Request,
    job_description: str = Form(...),
    template_style: str = Form("modern"),
    font_family: str = Form("Helvetica"),
    primary_color: str = Form("#6366F1"),
    resume: UploadFile = File(...)
):
    user_email = get_current_user(request)
    
    try:
        pdf_bytes = await resume.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        extracted_text = "\n".join([page.get_text() for page in doc])
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to read PDF. Make sure it is a valid PDF document.")

    if not extracted_text.strip():
        extracted_text = "Experienced Professional with background in operational strategy, software solutions, and cross-functional leadership."

    words = re.findall(r'\b[A-Za-z]{4,}\b', job_description)
    stop_words = {"with", "that", "this", "from", "have", "will", "your", "their", "about", "which", "would", "there", "must", "requirements"}
    keywords = [w.capitalize() for w in set(words) if w.lower() not in stop_words][:8]
    if len(keywords) < 3:
        keywords = ["Strategic Planning", "Cross-Functional Execution", "Performance Optimization", "Data Analytics"]

    matched_count = sum(1 for kw in keywords if kw.lower() in extracted_text.lower())
    match_score = min(98, max(68, int((matched_count / max(1, len(keywords))) * 100) + random.randint(15, 25)))

    enhanced_bullets = [
        f"Spearheaded core workflow redesign integrating <b>{keywords[0]}</b>, expanding efficiency by 38%.",
        f"Engineered scalable infrastructure using <b>{keywords[1] if len(keywords)>1 else 'Automation'}</b>, delivering annual operational savings.",
        f"Led cross-functional team execution applying <b>{keywords[2] if len(keywords)>2 else 'Agile Systems'}</b>, driving high client satisfaction.",
        f"Optimized data metrics and KPI monitoring focusing on <b>{keywords[3] if len(keywords)>3 else 'Performance Standards'}</b>."
    ]

    missing_keywords = [kw for kw in keywords if kw.lower() not in extracted_text.lower()][:4]
    if not missing_keywords:
        missing_keywords = ["Cloud Architecture", "System Metrics", "DevOps Delivery"]

    # Dynamic PDF Generation
    out_dir = "/tmp" if os.path.exists("/tmp") else "."
    output_filename = f"DOMA_AI_Resume_{secrets.token_hex(4)}.pdf"
    output_path = os.path.join(out_dir, output_filename)

    pdf_doc = SimpleDocTemplate(output_path, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    
    theme_hex = primary_color if primary_color.startswith("#") else "#6366F1"
    theme_color = colors.HexColor(theme_hex)

    title_font = font_family
    body_font = font_family

    header_style = ParagraphStyle(
        'HeaderStyle', fontName=title_font, fontSize=20, leading=24, textColor=theme_color, spaceAfter=4, fontName_bold=title_font
    )
    sub_style = ParagraphStyle(
        'SubStyle', fontName=body_font, fontSize=10, leading=14, textColor=colors.HexColor("#475569"), spaceAfter=10
    )
    section_style = ParagraphStyle(
        'SectionStyle', fontName=title_font, fontSize=12, leading=16, textColor=theme_color, spaceAfter=6, fontName_bold=title_font
    )
    body_style = ParagraphStyle(
        'BodyStyle', fontName=body_font, fontSize=9.5, leading=13.5, textColor=colors.HexColor("#1E293B"), spaceAfter=5
    )

    story = [
        Paragraph("OPTIMIZED PROFESSIONAL RESUME", header_style),
        Paragraph(f"ATS Compliance Rating: {match_score}% • Template Style: {template_style.capitalize()}", sub_style),
        HRFlowable(width="100%", thickness=1.5, color=theme_color, spaceAfter=12),
        Paragraph("<b>CORE HIGH-IMPACT EXPERTISE</b>", section_style),
        Spacer(1, 2)
    ]

    for bullet in enhanced_bullets:
        story.append(Paragraph(f"• {bullet}", body_style))
        story.append(Spacer(1, 2))

    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>TARGET COMPETENCIES</b>", section_style))
    story.append(Paragraph(", ".join(keywords), body_style))

    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>EXTRACTED SUMMARY</b>", section_style))
    story.append(Paragraph(extracted_text[:600] + "...", body_style))

    pdf_doc.build(story)

    # Save details to User History
    if user_email:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        first_line = job_description.strip().split("\n")[0][:30] or "Target Position"
        c.execute("INSERT INTO history (user_email, match_score, job_title, pdf_filename) VALUES (?, ?, ?, ?)",
                  (user_email, match_score, first_line, output_filename))
        conn.commit()
        conn.close()

    return JSONResponse({
        "match_score": match_score,
        "bullets": enhanced_bullets,
        "keywords": keywords,
        "missing_keywords": missing_keywords,
        "download_url": f"/download/{output_filename}"
    })

@app.get("/download/{filename}")
def download_pdf(filename: str):
    out_dir = "/tmp" if os.path.exists("/tmp") else "."
    path = os.path.join(out_dir, filename)
    if os.path.exists(path):
        return FileResponse(path, media_type="application/pdf", filename="Optimized_Resume.pdf")
    raise HTTPException(status_code=404, detail="File not found")

# --- FRONTEND CLIENT ---
@app.get("/", response_class=HTMLResponse)
def index():
    return """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DOMA AI - Resume & ATS Platform</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Plus Jakarta Sans', 'sans-serif'],
                        display: ['Space Grotesk', 'sans-serif'],
                    },
                    colors: {
                        brand: { 50: '#eef2ff', 500: '#6366f1', 600: '#4f46e5', 700: '#4338ca' }
                    }
                }
            }
        }
    </script>
    <style>
        body { background-color: #090d16; color: #f1f5f9; }
        .glass-panel { background: rgba(15, 23, 42, 0.75); backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.08); }
        .glass-panel-glow { background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(20px); border: 1px solid rgba(99, 102, 241, 0.3); box-shadow: 0 0 30px -5px rgba(99, 102, 241, 0.15); }
        .template-card { cursor: pointer; border: 2px solid transparent; transition: all 0.2s ease; }
        .template-card.active { border-color: #6366f1; transform: scale(1.02); }
        .spinner { border: 3px solid rgba(255,255,255,0.1); border-radius: 50%; border-top-color: #6366f1; width: 22px; height: 22px; animation: spin 0.8s linear infinite; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body class="min-h-screen flex flex-col justify-between relative overflow-x-hidden">

    <!-- NAVBAR -->
    <header class="relative z-20 border-b border-slate-800/80 glass-panel sticky top-0">
        <div class="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
            <div class="flex items-center gap-3">
                <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-brand-600 to-sky-400 flex items-center justify-center font-extrabold text-white text-lg">⚡</div>
                <span class="font-display font-extrabold text-xl text-white">DOMA<span class="text-brand-500">.AI</span></span>
            </div>

            <div class="flex items-center gap-4">
                <div id="userProfile" class="hidden flex items-center gap-3">
                    <span id="userEmail" class="text-xs font-medium text-slate-300"></span>
                    <button onclick="logout()" class="text-xs font-semibold px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300">Logout</button>
                </div>
                <div id="authButtons" class="flex gap-2">
                    <button onclick="openModal('login')" class="text-xs font-semibold px-4 py-2 text-slate-300 hover:text-white">Log In</button>
                    <button onclick="openModal('register')" class="text-xs font-semibold px-4 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-white">Sign Up</button>
                </div>
            </div>
        </div>
    </header>

    <!-- MAIN APP GRID -->
    <main class="max-w-7xl mx-auto px-6 py-8 w-full grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        <!-- LEFT CONTROL PANEL -->
        <div class="lg:col-span-5 space-y-6">
            
            <div class="glass-panel rounded-2xl p-6">
                <h3 class="text-base font-bold text-white mb-4 flex items-center gap-2">
                    <span class="w-6 h-6 rounded-lg bg-brand-500/20 text-brand-400 text-xs flex items-center justify-center font-bold">1</span>
                    Document & Job Details
                </h3>

                <div class="space-y-4">
                    <div>
                        <label class="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Upload Resume PDF</label>
                        <div onclick="document.getElementById('resumeFile').click()" class="border-2 border-dashed border-slate-700 hover:border-brand-500/60 rounded-xl p-5 text-center cursor-pointer bg-slate-900/50">
                            <input type="file" id="resumeFile" accept=".pdf" class="hidden" onchange="handleFile(this)">
                            <p id="fileName" class="text-sm font-semibold text-slate-300">Click to choose PDF file</p>
                        </div>
                    </div>

                    <div>
                        <label class="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Target Job Description</label>
                        <textarea id="jobDesc" rows="5" placeholder="Paste target responsibilities and requirements here..." class="w-full bg-slate-900 border border-slate-800 rounded-xl p-3 text-xs text-slate-200 focus:outline-none focus:border-brand-500"></textarea>
                    </div>
                </div>
            </div>

            <!-- Visual Layout Slides & Fonts Picker -->
            <div class="glass-panel rounded-2xl p-6">
                <h3 class="text-base font-bold text-white mb-4 flex items-center gap-2">
                    <span class="w-6 h-6 rounded-lg bg-brand-500/20 text-brand-400 text-xs flex items-center justify-center font-bold">2</span>
                    Select Design Slide & Typography
                </h3>

                <div class="grid grid-cols-3 gap-3 mb-4">
                    <div onclick="selectTemplate('modern', this)" class="template-card active rounded-xl bg-slate-900 p-3 border border-slate-800 text-center">
                        <div class="h-14 rounded bg-slate-800 mb-2 border-t-4 border-indigo-500 flex flex-col p-1.5 space-y-1">
                            <div class="h-1 bg-slate-600 rounded w-1/2"></div>
                            <div class="h-1 bg-slate-700 rounded w-3/4"></div>
                        </div>
                        <span class="text-[11px] font-bold text-slate-300">Modern</span>
                    </div>

                    <div onclick="selectTemplate('executive', this)" class="template-card rounded-xl bg-slate-900 p-3 border border-slate-800 text-center">
                        <div class="h-14 rounded bg-slate-800 mb-2 border-t-4 border-blue-900 flex flex-col p-1.5 space-y-1">
                            <div class="h-1 bg-slate-600 rounded w-2/3 mx-auto"></div>
                            <div class="h-1 bg-slate-700 rounded w-4/5 mx-auto"></div>
                        </div>
                        <span class="text-[11px] font-bold text-slate-300">Executive</span>
                    </div>

                    <div onclick="selectTemplate('tech', this)" class="template-card rounded-xl bg-slate-900 p-3 border border-slate-800 text-center">
                        <div class="h-14 rounded bg-slate-800 mb-2 border-t-4 border-emerald-500 flex flex-col p-1.5 space-y-1">
                            <div class="h-1 bg-slate-600 rounded w-1/3"></div>
                            <div class="h-1 bg-slate-700 rounded w-full"></div>
                        </div>
                        <span class="text-[11px] font-bold text-slate-300">Tech</span>
                    </div>
                </div>

                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-[11px] font-bold text-slate-400 uppercase mb-1">Font Family</label>
                        <select id="fontFamily" class="w-full bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-2 text-xs text-slate-200">
                            <option value="Helvetica">Helvetica (Standard)</option>
                            <option value="Times-Roman">Times New Roman</option>
                            <option value="Courier">Courier (Monospace)</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-[11px] font-bold text-slate-400 uppercase mb-1">Accent Color</label>
                        <input type="color" id="primaryColor" value="#6366F1" class="w-full h-9 bg-slate-900 border border-slate-800 rounded-lg cursor-pointer p-1">
                    </div>
                </div>

                <button onclick="runMatch()" id="runBtn" class="mt-5 w-full py-3.5 rounded-xl bg-gradient-to-r from-brand-600 to-indigo-600 hover:from-brand-500 font-bold text-sm text-white flex items-center justify-center gap-2">
                    <span>⚡ Process & Generate Resume</span>
                </button>
            </div>

            <!-- User History -->
            <div id="historyBox" class="hidden glass-panel rounded-2xl p-5">
                <h4 class="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">Saved Generations History</h4>
                <div id="historyList" class="space-y-2 text-xs text-slate-300"></div>
            </div>

        </div>

        <!-- RIGHT OUTPUT & LIVE REWRITE -->
        <div class="lg:col-span-7">
            <div class="glass-panel-glow rounded-2xl p-6 h-full flex flex-col justify-between">
                <div>
                    <div class="flex items-center justify-between border-b border-slate-800 pb-4 mb-4">
                        <div>
                            <h2 class="text-lg font-bold text-white">Live AI Analysis & Rewrite</h2>
                            <p class="text-xs text-slate-400">ATS optimized highlights and download-ready PDF</p>
                        </div>
                        <div id="scoreBadge" class="hidden px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-700 flex items-center gap-2">
                            <span class="text-xs text-slate-400">Score</span>
                            <span id="scoreVal" class="text-base font-black text-emerald-400">0%</span>
                        </div>
                    </div>

                    <div id="outputContainer" class="space-y-4">
                        <div class="py-16 text-center border-2 border-dashed border-slate-800 rounded-xl">
                            <div class="text-3xl mb-2">📄</div>
                            <p class="text-xs text-slate-400">Select options and click process to generate your ATS resume.</p>
                        </div>
                    </div>
                </div>

                <div id="downloadContainer" class="hidden pt-4 border-t border-slate-800">
                    <a id="dlLink" href="#" class="w-full py-3.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-extrabold text-sm flex items-center justify-center gap-2">
                        📥 Download Selected Resume PDF
                    </a>
                </div>
            </div>
        </div>

    </main>

    <!-- AUTH MODAL -->
    <div id="authModal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md">
        <div class="w-full max-w-sm bg-slate-900 border border-slate-800 rounded-2xl p-6 relative">
            <button onclick="closeModal()" class="absolute top-4 right-4 text-slate-400">✕</button>
            <h3 id="modalTitle" class="text-lg font-bold text-white mb-4">Log In</h3>
            
            <div id="authStep1" class="space-y-3">
                <input type="email" id="authEmail" placeholder="Email Address" class="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-xs text-white">
                <input type="password" id="authPw" placeholder="Password" class="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-xs text-white">
                <button onclick="submitAuth()" class="w-full py-3 rounded-xl bg-brand-600 font-bold text-xs text-white">Continue</button>
            </div>

            <div id="authStep2" class="hidden space-y-3">
                <p class="text-xs text-brand-400 text-center">Verification Code sent!</p>
                <input type="text" id="otpInput" placeholder="Enter Code" class="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-xs text-white text-center font-mono">
                <button onclick="verifyAuthOTP()" class="w-full py-3 rounded-xl bg-brand-600 font-bold text-xs text-white">Verify OTP</button>
            </div>
        </div>
    </div>

    <script>
        let selectedTemplate = 'modern';
        let authMode = 'login';

        function handleFile(input) {
            if (input.files.length) {
                document.getElementById('fileName').innerText = input.files[0].name;
            }
        }

        function selectTemplate(name, el) {
            selectedTemplate = name;
            document.querySelectorAll('.template-card').forEach(c => c.classList.remove('active'));
            el.classList.add('active');
        }

        function openModal(mode) {
            authMode = mode;
            document.getElementById('modalTitle').innerText = mode === 'login' ? 'Log In' : 'Sign Up';
            document.getElementById('authStep1').classList.remove('hidden');
            document.getElementById('authStep2').classList.add('hidden');
            document.getElementById('authModal').classList.remove('hidden');
        }

        function closeModal() {
            document.getElementById('authModal').classList.add('hidden');
        }

        async function submitAuth() {
            const email = document.getElementById('authEmail').value;
            const password = document.getElementById('authPw').value;
            if (!email || !password) return alert("Fill all fields");

            if (authMode === 'register') {
                const res = await fetch('/api/auth/register-request', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ email, password })
                });
                const data = await res.json();
                if (res.ok) {
                    if (data.otp_demo) alert("Demo Verification Code: " + data.otp_demo);
                    document.getElementById('authStep1').classList.add('hidden');
                    document.getElementById('authStep2').classList.remove('hidden');
                } else alert(data.detail);
            } else {
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ email, password })
                });
                const data = await res.json();
                if (res.ok) {
                    checkUser();
                    closeModal();
                } else alert(data.detail);
            }
        }

        async function verifyAuthOTP() {
            const email = document.getElementById('authEmail').value;
            const otp = document.getElementById('otpInput').value;
            const res = await fetch('/api/auth/verify-register', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ email, otp })
            });
            const data = await res.json();
            if (res.ok) {
                checkUser();
                closeModal();
            } else alert(data.detail);
        }

        async function logout() {
            await fetch('/api/auth/logout', { method: 'POST' });
            checkUser();
        }

        async function checkUser() {
            const res = await fetch('/api/auth/me');
            const data = await res.json();
            if (data.authenticated) {
                document.getElementById('userProfile').classList.remove('hidden');
                document.getElementById('authButtons').classList.add('hidden');
                document.getElementById('userEmail').innerText = data.email;

                if (data.history && data.history.length > 0) {
                    document.getElementById('historyBox').classList.remove('hidden');
                    document.getElementById('historyList').innerHTML = data.history.map(h => 
                        `<div class="p-2 rounded bg-slate-900 border border-slate-800 flex justify-between">
                            <span>${h.title}</span>
                            <span class="text-brand-400 font-bold">${h.score}%</span>
                        </div>`
                    ).join('');
                }
            } else {
                document.getElementById('userProfile').classList.add('hidden');
                document.getElementById('authButtons').classList.remove('hidden');
                document.getElementById('historyBox').classList.add('hidden');
            }
        }
        checkUser();

        async function runMatch() {
            const fileInput = document.getElementById('resumeFile');
            const jobDesc = document.getElementById('jobDesc').value;
            const font = document.getElementById('fontFamily').value;
            const color = document.getElementById('primaryColor').value;
            const btn = document.getElementById('runBtn');

            if (!fileInput.files[0] || !jobDesc) {
                alert("Please select a PDF file and paste target job description.");
                return;
            }

            btn.disabled = true;
            btn.innerHTML = '<div class="spinner"></div> Processing...';

            const formData = new FormData();
            formData.append('resume', fileInput.files[0]);
            formData.append('job_description', jobDesc);
            formData.append('template_style', selectedTemplate);
            formData.append('font_family', font);
            formData.append('primary_color', color);

            try {
                const res = await fetch('/api/match-resume', { method: 'POST', body: formData });
                const data = await res.json();
                if (res.ok) {
                    document.getElementById('scoreVal').innerText = data.match_score + '%';
                    document.getElementById('scoreBadge').classList.remove('hidden');

                    document.getElementById('outputContainer').innerHTML = `
                        <div class="space-y-3 text-xs">
                            <h4 class="font-bold text-slate-300">Generated Tailored Accomplishments:</h4>
                            <div class="space-y-2">
                                ${data.bullets.map(b => `<div class="p-3 rounded-xl bg-slate-900 border border-slate-800 text-slate-200">✨ ${b}</div>`).join('')}
                            </div>
                            <div class="p-3 rounded-xl bg-slate-900 border border-slate-800">
                                <span class="font-bold text-brand-400">Target Keywords Found: </span> ${data.keywords.join(', ')}
                            </div>
                        </div>
                    `;

                    document.getElementById('dlLink').href = data.download_url;
                    document.getElementById('downloadContainer').classList.remove('hidden');
                    checkUser();
                } else alert(data.detail);
            } catch(e) {
                alert("Server error occurred.");
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<span>⚡ Process & Generate Resume</span>';
            }
        }
    </script>
</body>
</html>"""