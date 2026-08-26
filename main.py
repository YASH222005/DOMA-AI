import io
import re
from typing import List, Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse
import pypdf
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

from models import init_db, User, SessionLocal
from auth import router as auth_router, get_current_user, get_db

# Initialize database tables
init_db()

app = FastAPI(title="DOMA AI - Resume Matcher & Rewriter")
app.include_router(auth_router)

# --- RESUME ANALYSIS ENGINE ---
def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    text = ""
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            text += extracted + " "
    return text

def extract_keywords_from_jd(jd_text: str) -> List[str]:
    raw_words = re.findall(r'\b[A-Za-z0-9+#.-]{3,}\b', jd_text)
    ignore_set = {"and", "the", "for", "with", "that", "this", "from", "have", "you", "are", "will", "our", "work", "team"}
    unique_words = list(dict.fromkeys([w for w in raw_words if w.lower() not in ignore_set]))
    return unique_words[:25]

def generate_optimized_bullets(missing_keywords: List[str]) -> List[str]:
    bullets = []
    if missing_keywords:
        kw1 = missing_keywords[0] if len(missing_keywords) > 0 else "key metrics"
        kw2 = missing_keywords[1] if len(missing_keywords) > 1 else "workflows"
        bullets.append(f"Optimized core operational processes utilizing {kw1} and {kw2} to enhance overall project performance and output quality.")
    if len(missing_keywords) > 2:
        kw3 = missing_keywords[2]
        kw4 = missing_keywords[3] if len(missing_keywords) > 3 else "best practices"
        bullets.append(f"Implemented scalable solution architectures focusing on {kw3} while aligning with company standards for {kw4}.")
    if len(missing_keywords) > 4:
        kw5 = missing_keywords[4]
        bullets.append(f"Spearheaded cross-functional initiatives leveraging {kw5} to maximize efficiency and achieve target deliverables ahead of schedule.")
    if not bullets:
        bullets.append("Collaborated with cross-functional teams to streamline project lifecycles and increase core performance metrics by 25%.")
    return bullets

def generate_pdf_bytes(title: str, content_bullets: List[str], missing_kw: List[str]) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=0.75*inch, leftMargin=0.75*inch, topMargin=0.75*inch, bottomMargin=0.75*inch)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontSize=20, leading=24, spaceAfter=12, textColor='#1e293b')
    sub_style = ParagraphStyle('DocSub', parent=styles['Heading2'], fontSize=14, leading=18, spaceAfter=8, textColor='#3b82f6')
    body_style = ParagraphStyle('DocBody', parent=styles['BodyText'], fontSize=10, leading=14, spaceAfter=6, textColor='#334155')

    story = [
        Paragraph(f"Optimized Resume Summary - {title}", title_style),
        Spacer(1, 0.1*inch),
        Paragraph("Key Skills Integrated:", sub_style),
        Paragraph(", ".join(missing_kw) if missing_kw else "All keywords present.", body_style),
        Spacer(1, 0.15*inch),
        Paragraph("Tailored Experience Bullet Points:", sub_style)
    ]

    for bullet in content_bullets:
        story.append(Paragraph(f"• {bullet}", body_style))
        story.append(Spacer(1, 0.05*inch))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

# --- API ENDPOINTS ---
@app.post("/analyze")
async def analyze_resume(
    jd_text: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db = Depends(get_db)
):
    if not current_user.is_unlimited and current_user.coins < 1:
        raise HTTPException(status_code=402, detail="Insufficient coin balance. Please upgrade your plan.")

    pdf_bytes = await file.read()
    resume_text = extract_text_from_pdf(pdf_bytes)
    jd_keywords = extract_keywords_from_jd(jd_text)

    matched = [kw for kw in jd_keywords if kw.lower() in resume_text.lower()]
    missing = [kw for kw in jd_keywords if kw.lower() not in resume_text.lower()]

    match_score = int((len(matched) / len(jd_keywords)) * 100) if jd_keywords else 100
    suggested_bullets = generate_optimized_bullets(missing)

    # Deduct credit if not unlimited
    if not current_user.is_unlimited:
        current_user.coins -= 1
        db.commit()

    return {
        "score": match_score,
        "matched": matched,
        "missing": missing,
        "bullets": suggested_bullets,
        "remaining_coins": current_user.coins,
        "is_unlimited": current_user.is_unlimited
    }

@app.post("/download-pdf")
async def download_pdf(
    title: str = Form("DOMA AI Optimized"),
    missing: str = Form(""),
    bullets: str = Form(""),
    current_user: User = Depends(get_current_user)
):
    missing_list = [x.strip() for x in missing.split(",") if x.strip()]
    bullet_list = [x.strip() for x in bullets.split("\n") if x.strip()]
    
    pdf_data = generate_pdf_bytes(title, bullet_list, missing_list)
    return StreamingResponse(
        io.BytesIO(pdf_data),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=DOMA_AI_Resume_{title}.pdf"}
    )

# --- FRONTEND INTERFACE ---
@app.get("/", response_class=HTMLResponse)
def serve_ui():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>DOMA AI - Professional Resume Matcher & Rewriter</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    </head>
    <body class="bg-slate-900 text-slate-100 min-h-screen flex flex-col font-sans">
        <!-- Navigation Bar -->
        <nav class="border-b border-slate-800 bg-slate-950/80 backdrop-blur px-6 py-4 flex justify-between items-center sticky top-0 z-50">
            <div class="flex items-center space-x-3">
                <div class="bg-blue-600 text-white p-2 rounded-lg font-bold"><i class="fa-solid fa-wand-magic-sparkles"></i></div>
                <span class="text-xl font-bold tracking-tight">DOMA <span class="text-blue-500">AI</span></span>
            </div>
            
            <div id="auth-nav" class="flex items-center space-x-4">
                <div id="user-badge" class="hidden items-center bg-slate-800 px-3 py-1.5 rounded-full border border-slate-700 text-sm">
                    <i class="fa-solid fa-coins text-amber-400 mr-2"></i>
                    <span id="coin-count" class="font-bold text-amber-400">0</span>
                    <span class="ml-1 text-slate-400">Coins</span>
                </div>
                <button onclick="openModal('login-modal')" id="login-btn" class="text-sm font-semibold hover:text-blue-400 transition">Log In</button>
                <button onclick="openModal('signup-modal')" id="signup-btn" class="bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition">Sign Up Free</button>
                <button onclick="logout()" id="logout-btn" class="hidden text-sm text-red-400 hover:text-red-300 font-semibold transition">Log Out</button>
            </div>
        </nav>

        <!-- Main Workspace -->
        <main class="flex-1 max-w-7xl w-full mx-auto p-6 grid grid-cols-1 lg:grid-cols-2 gap-8">
            <!-- Left Panel: Inputs -->
            <div class="bg-slate-800/50 border border-slate-700/60 rounded-2xl p-6 flex flex-col justify-between space-y-6">
                <div>
                    <h2 class="text-lg font-semibold text-white mb-2"><i class="fa-solid fa-file-invoice text-blue-400 mr-2"></i>Target Job Description</h2>
                    <textarea id="jd_text" class="w-full h-44 bg-slate-900 border border-slate-700 rounded-xl p-4 text-sm text-slate-200 focus:outline-none focus:border-blue-500 transition resize-none" placeholder="Paste target job responsibilities and key requirements here..."></textarea>
                </div>

                <div>
                    <h2 class="text-lg font-semibold text-white mb-2"><i class="fa-solid fa-file-pdf text-blue-400 mr-2"></i>Upload Your Resume (PDF)</h2>
                    <label class="border-2 border-dashed border-slate-700 hover:border-blue-500 bg-slate-900/60 rounded-xl p-6 flex flex-col items-center justify-center cursor-pointer transition">
                        <i class="fa-solid fa-cloud-arrow-up text-3xl text-slate-400 mb-2"></i>
                        <span id="file-label" class="text-sm text-slate-300 font-medium">Click to select PDF or drag & drop</span>
                        <input type="file" id="resume_file" accept=".pdf" class="hidden" onchange="updateFileName(this)">
                    </label>
                </div>

                <button onclick="runAnalysis()" class="w-full bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-bold py-3.5 rounded-xl shadow-lg transition flex items-center justify-center space-x-2">
                    <i class="fa-solid fa-bolt"></i>
                    <span>Match & Auto-Rewrite Resume</span>
                </button>
            </div>

            <!-- Right Panel: Results -->
            <div class="bg-slate-800/50 border border-slate-700/60 rounded-2xl p-6 flex flex-col space-y-6">
                <h2 class="text-lg font-semibold text-white"><i class="fa-solid fa-chart-pie text-blue-400 mr-2"></i>Analysis & Generated Content</h2>
                
                <div id="results-placeholder" class="flex-1 flex flex-col items-center justify-center text-center p-8 border border-dashed border-slate-700 rounded-xl">
                    <i class="fa-solid fa-wand-magic-sparkles text-4xl text-slate-600 mb-3"></i>
                    <p class="text-slate-400 text-sm">Upload a resume and job description to view ATS compatibility and generate rewritten experience bullets.</p>
                </div>

                <div id="results-content" class="hidden flex-1 flex-col space-y-6">
                    <!-- Match Score Ring -->
                    <div class="flex items-center space-x-6 bg-slate-900/80 p-4 rounded-xl border border-slate-700">
                        <div class="text-center">
                            <span id="score-val" class="text-3xl font-extrabold text-blue-400">0%</span>
                            <p class="text-xs text-slate-400 uppercase font-bold tracking-wider mt-1">ATS Match</p>
                        </div>
                        <div class="flex-1">
                            <p class="text-xs font-semibold text-slate-300">Match Grade</p>
                            <div class="w-full bg-slate-800 h-2.5 rounded-full mt-2 overflow-hidden">
                                <div id="score-bar" class="bg-blue-500 h-2.5 rounded-full transition-all duration-500" style="width: 0%"></div>
                            </div>
                        </div>
                    </div>

                    <!-- Keywords -->
                    <div class="space-y-3">
                        <p class="text-xs font-bold uppercase tracking-wider text-slate-400">Missing Keywords Found</p>
                        <div id="missing-tags" class="flex flex-wrap gap-2"></div>
                    </div>

                    <!-- Rewritten Bullets -->
                    <div class="space-y-3 flex-1 flex flex-col">
                        <p class="text-xs font-bold uppercase tracking-wider text-slate-400">Generated Tailored Bullets</p>
                        <div id="bullets-list" class="bg-slate-900/80 p-4 rounded-xl border border-slate-700 text-sm space-y-2 text-slate-300 flex-1 overflow-y-auto max-h-48"></div>
                    </div>

                    <form action="/download-pdf" method="post" target="_blank" class="pt-2">
                        <input type="hidden" name="missing" id="form-missing">
                        <input type="hidden" name="bullets" id="form-bullets">
                        <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-3 rounded-xl transition flex items-center justify-center space-x-2">
                            <i class="fa-solid fa-file-arrow-down"></i>
                            <span>Download Rewritten PDF Resume</span>
                        </button>
                    </form>
                </div>
            </div>
        </main>

        <!-- Login Modal -->
        <div id="login-modal" class="fixed inset-0 bg-black/70 hidden items-center justify-center p-4 z-50">
            <div class="bg-slate-800 border border-slate-700 p-6 rounded-2xl max-w-sm w-full space-y-4">
                <div class="flex justify-between items-center">
                    <h3 class="text-lg font-bold text-white">Log In to DOMA AI</h3>
                    <button onclick="closeModal('login-modal')" class="text-slate-400 hover:text-white"><i class="fa-solid fa-xmark"></i></button>
                </div>
                <input id="login-email" type="email" placeholder="Email Address" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-sm text-white focus:outline-none focus:border-blue-500">
                <input id="login-pass" type="password" placeholder="Password" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-sm text-white focus:outline-none focus:border-blue-500">
                <button onclick="handleLogin()" class="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-2.5 rounded-lg transition">Log In</button>
            </div>
        </div>

        <!-- Signup Modal -->
        <div id="signup-modal" class="fixed inset-0 bg-black/70 hidden items-center justify-center p-4 z-50">
            <div class="bg-slate-800 border border-slate-700 p-6 rounded-2xl max-w-sm w-full space-y-4">
                <div class="flex justify-between items-center">
                    <h3 class="text-lg font-bold text-white">Create Account</h3>
                    <button onclick="closeModal('signup-modal')" class="text-slate-400 hover:text-white"><i class="fa-solid fa-xmark"></i></button>
                </div>
                <input id="signup-email" type="email" placeholder="Email Address" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-sm text-white focus:outline-none focus:border-blue-500">
                <input id="signup-pass" type="password" placeholder="Password" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-sm text-white focus:outline-none focus:border-blue-500">
                <button onclick="handleSignup()" class="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-2.5 rounded-lg transition">Create Account (+5 Free Coins)</button>
            </div>
        </div>

        <script>
            let authToken = localStorage.getItem('token');

            function updateFileName(input) {
                if(input.files[0]) {
                    document.getElementById('file-label').innerText = input.files[0].name;
                }
            }

            function openModal(id) { document.getElementById(id).classList.remove('hidden'); document.getElementById(id).classList.add('flex'); }
            function closeModal(id) { document.getElementById(id).classList.add('hidden'); document.getElementById(id).classList.remove('flex'); }

            function checkAuthState() {
                if(authToken) {
                    document.getElementById('login-btn').classList.add('hidden');
                    document.getElementById('signup-btn').classList.add('hidden');
                    document.getElementById('logout-btn').classList.remove('hidden');
                    document.getElementById('user-badge').classList.remove('hidden');
                    document.getElementById('user-badge').classList.add('flex');
                    document.getElementById('coin-count').innerText = localStorage.getItem('coins') || '5';
                }
            }

            function logout() {
                localStorage.clear();
                location.reload();
            }

            async function handleSignup() {
                const email = document.getElementById('signup-email').value;
                const pass = document.getElementById('signup-pass').value;
                const body = new URLSearchParams({ username: email, password: pass });
                const res = await fetch('/auth/signup', { method: 'POST', body });
                if(res.ok) {
                    const data = await res.json();
                    localStorage.setItem('token', data.access_token);
                    localStorage.setItem('coins', data.coins);
                    location.reload();
                } else {
                    alert('Signup failed. Email may already exist.');
                }
            }

            async function handleLogin() {
                const email = document.getElementById('login-email').value;
                const pass = document.getElementById('login-pass').value;
                const body = new URLSearchParams({ username: email, password: pass });
                const res = await fetch('/auth/login', { method: 'POST', body });
                if(res.ok) {
                    const data = await res.json();
                    localStorage.setItem('token', data.access_token);
                    localStorage.setItem('coins', data.coins);
                    location.reload();
                } else {
                    alert('Login failed. Check your details.');
                }
            }

            async function runAnalysis() {
                if(!authToken) {
                    alert('Please log in or sign up first to use coins!');
                    openModal('signup-modal');
                    return;
                }

                const jd = document.getElementById('jd_text').value;
                const file = document.getElementById('resume_file').files[0];
                if(!jd || !file) {
                    alert('Please paste a job description and select a PDF file.');
                    return;
                }

                const formData = new FormData();
                formData.append('jd_text', jd);
                formData.append('file', file);

                const res = await fetch('/analyze', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + authToken },
                    body: formData
                });

                if(res.ok) {
                    const data = await res.json();
                    localStorage.setItem('coins', data.remaining_coins);
                    document.getElementById('coin-count').innerText = data.remaining_coins;

                    document.getElementById('results-placeholder').classList.add('hidden');
                    document.getElementById('results-content').classList.remove('hidden');
                    document.getElementById('results-content').classList.add('flex');

                    document.getElementById('score-val').innerText = data.score + '%';
                    document.getElementById('score-bar').style.width = data.score + '%';

                    const tags = document.getElementById('missing-tags');
                    tags.innerHTML = '';
                    data.missing.forEach(kw => {
                        tags.innerHTML += `<span class="bg-red-500/20 text-red-300 text-xs px-2.5 py-1 rounded-full border border-red-500/30">${kw}</span>`;
                    });

                    const bullets = document.getElementById('bullets-list');
                    bullets.innerHTML = '';
                    data.bullets.forEach(b => {
                        bullets.innerHTML += `<p class="leading-relaxed">• ${b}</p>`;
                    });

                    document.getElementById('form-missing').value = data.missing.join(',');
                    document.getElementById('form-bullets').value = data.bullets.join('\n');
                } else if(res.status === 402) {
                    alert('You ran out of coins! Upgrade to continue.');
                } else {
                    alert('Analysis failed. Try again.');
                }
            }

            checkAuthState();
        </script>
    </body>
    </html>
    """