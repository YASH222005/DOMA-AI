import os
import re
import random
import string
import secrets
import smtplib
from email.mime.text import MIMEText
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import fitz  # PyMuPDF

app = FastAPI(title="DOMA AI - Resume Matcher")

# --- SMTP EMAIL CONFIGURATION ---
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "your-email@gmail.com")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "your-app-password")

def send_email(to_email: str, subject: str, body: str):
    if SENDER_EMAIL == "your-email@gmail.com":
        print(f"[DEMO LOG] Email to {to_email} | Subject: {subject}\nBody: {body}")
        return
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"Error sending email: {e}")

# --- IN-MEMORY DATABASE ---
users_db = {}        # email -> {password, coins, verified}
otp_store = {}       # email -> otp_code
reset_tokens = {}    # token -> email

def is_strong_password(pw: str) -> bool:
    pattern = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$"
    return bool(re.match(pattern, pw))

# --- AUTH MODELS ---
class OTPRequest(BaseModel):
    email: EmailStr
    password: str

class OTPVerify(BaseModel):
    email: EmailStr
    otp: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

# --- AUTH ENDPOINTS ---
@app.post("/api/auth/request-otp")
def request_otp(data: OTPRequest):
    if not is_strong_password(data.password):
        raise HTTPException(status_code=400, detail="Password must be at least 8 chars long with 1 uppercase, 1 lowercase, 1 digit, and 1 special char.")
    otp = "".join(random.choices(string.digits, k=6))
    otp_store[data.email] = {"otp": otp, "password": data.password}
    send_email(data.email, "Your DOMA AI Verification Code", f"Your verification code is: {otp}")
    return {"message": "Verification code sent to your email."}

@app.post("/api/auth/verify-otp")
def verify_otp(data: OTPVerify):
    record = otp_store.get(data.email)
    if not record or record["otp"] != data.otp:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
    
    users_db[data.email] = {
        "password": record["password"],
        "coins": 5,
        "verified": True
    }
    del otp_store[data.email]
    return {"message": "Account successfully verified and created!", "email": data.email, "coins": 5}

@app.post("/api/auth/login")
def login(data: LoginRequest):
    user = users_db.get(data.email)
    if not user or user["password"] != data.password:
        raise HTTPException(status_code=400, detail="Invalid email or password.")
    return {"message": "Login successful", "email": data.email, "coins": user["coins"]}

@app.post("/api/auth/forgot-password")
def forgot_password(data: ForgotPasswordRequest):
    if data.email not in users_db:
        raise HTTPException(status_code=404, detail="No account registered with this email.")
    token = secrets.token_urlsafe(32)
    reset_tokens[token] = data.email
    reset_link = f"https://doma-ai.onrender.com/?reset_token={token}"
    send_email(data.email, "Reset Your DOMA AI Password", f"Click here to reset your password: {reset_link}")
    return {"message": "Password reset link sent to your email."}

@app.post("/api/auth/reset-password")
def reset_password(data: ResetPasswordRequest):
    email = reset_tokens.get(data.token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")
    if not is_strong_password(data.new_password):
        raise HTTPException(status_code=400, detail="New password does not meet security requirements.")
    
    users_db[email]["password"] = data.new_password
    del reset_tokens[data.token]
    return {"message": "Password updated successfully. You can now log in."}

# --- RESUME PROCESSING & PDF GENERATION ---
@app.post("/api/match-resume")
async def match_resume(
    job_description: str = Form(...),
    template_style: str = Form("modern"),
    font_family: str = Form("Helvetica"),
    resume: UploadFile = File(...)
):
    # Extract text from uploaded PDF
    pdf_bytes = await resume.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    extracted_text = "\n".join([page.get_text() for page in doc])

    # Simple AI bullet enhancement generator
    jd_words = [w.strip() for w in re.findall(r'\b\w{5,}\b', job_description)]
    keywords = list(set(jd_words))[:5]
    
    enhanced_bullets = [
        f"Optimized project workflows utilizing {keywords[0] if len(keywords)>0 else 'industry standards'} to increase efficiency by 35%.",
        f"Engineered scalable solutions tailored to {keywords[1] if len(keywords)>1 else 'core deliverables'}, reducing downtime significantly.",
        f"Collaborated across teams to integrate {keywords[2] if len(keywords)>2 else 'key frameworks'}, improving throughput and reliability."
    ]

    # Generate customized PDF output
    output_filename = f"rewritten_{secrets.token_hex(4)}.pdf"
    output_path = os.path.join("/tmp", output_filename) if os.path.exists("/tmp") else output_filename
    
    pdf_doc = SimpleDocTemplate(output_path, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    
    primary_color = colors.HexColor("#00F2FE") if template_style == "tech" else colors.HexColor("#1E293B")
    
    title_style = ParagraphStyle(
        'TitleStyle',
        fontName=font_family,
        fontSize=20,
        leading=24,
        textColor=primary_color,
        spaceAfter=12
    )
    
    body_style = ParagraphStyle(
        'BodyStyle',
        fontName=font_family,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceAfter=8
    )

    story = [
        Paragraph("AI ENHANCED PROFESSIONAL RESUME", title_style),
        HRFlowable(width="100%", thickness=1.5, color=primary_color, spaceAfter=15),
        Paragraph("<b>Target Job Alignment Bullets:</b>", body_style),
        Spacer(1, 5)
    ]

    for bullet in enhanced_bullets:
        story.append(Paragraph(f"• {bullet}", body_style))
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 15))
    story.append(Paragraph("<b>Original Resume Summary:</b>", body_style))
    story.append(Paragraph(extracted_text[:600] + "...", body_style))

    pdf_doc.build(story)
    
    return JSONResponse({
        "bullets": enhanced_bullets,
        "download_url": f"/download/{output_filename}"
    })

@app.get("/download/{filename}")
def download_pdf(filename: str):
    path = os.path.join("/tmp", filename) if os.path.exists("/tmp") else filename
    if os.path.exists(path):
        return FileResponse(path, media_type="application/pdf", filename="Rewritten_Resume.pdf")
    raise HTTPException(status_code=404, detail="File not found")

# --- FRONTEND HTML (FROST & CRYSTAL UI + IMAGINEART OVERLAY) ---
@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DOMA AI - Premium Resume Matcher</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;600;800&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: #030712;
            color: #F3F4F6;
            overflow-x: hidden;
        }
        .frost-glass {
            background: rgba(15, 23, 42, 0.65);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(0, 242, 254, 0.2);
            box-shadow: 0 8px 32px 0 rgba(0, 242, 254, 0.1);
        }
        .neon-glow {
            box-shadow: 0 0 20px rgba(0, 242, 254, 0.35);
        }
        .neon-border:focus {
            border-color: #00F2FE;
            box-shadow: 0 0 15px rgba(0, 242, 254, 0.5);
        }
        canvas#snowCanvas {
            position: fixed;
            top: 0;
            left: 0;
            pointer-events: none;
            z-index: 1;
        }
        .crystal-leaf {
            position: absolute;
            pointer-events: none;
            opacity: 0.15;
            animation: float 12s infinite ease-in-out;
        }
        @keyframes float {
            0%, 100% { transform: translateY(0) rotate(0deg); }
            50% { transform: translateY(-20px) rotate(180deg); }
        }
    </style>
</head>
<body class="relative min-h-screen flex flex-col justify-between">

    <canvas id="snowCanvas"></canvas>

    <!-- Floating Crystal Maple Leaf Background Accents -->
    <svg class="crystal-leaf top-10 left-10 w-24 h-24 text-cyan-400" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2L9.5 8.5H2L7.5 12.5L5.5 19L12 15L18.5 19L16.5 12.5L22 8.5H14.5L12 2Z"/></svg>
    <svg class="crystal-leaf bottom-20 right-12 w-32 h-32 text-cyan-300" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2L9.5 8.5H2L7.5 12.5L5.5 19L12 15L18.5 19L16.5 12.5L22 8.5H14.5L12 2Z"/></svg>

    <!-- Header Navigation -->
    <header class="relative z-10 flex justify-between items-center px-8 py-5 frost-glass sticky top-0">
        <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-blue-600 flex items-center justify-center font-extrabold text-xl neon-glow">❄️</div>
            <span class="text-2xl font-extrabold tracking-wider bg-clip-text text-transparent bg-gradient-to-r from-cyan-400 to-blue-400">DOMA AI</span>
        </div>
        <div class="flex items-center gap-4">
            <span id="userBadge" class="hidden px-4 py-1.5 rounded-full bg-cyan-950/80 border border-cyan-500/30 text-cyan-300 text-sm font-semibold">🪙 <span id="coinCount">5</span> Coins</span>
            <button onclick="openAuthModal('login')" class="px-5 py-2 text-sm font-semibold text-gray-300 hover:text-cyan-400 transition">Log In</button>
            <button onclick="openAuthModal('signup')" class="px-6 py-2.5 text-sm font-bold rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 neon-glow transition">Sign Up Free</button>
        </div>
    </header>

    <!-- Main Workspace -->
    <main class="relative z-10 max-w-7xl mx-auto px-6 py-10 w-full grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        <!-- Controls & Options Column -->
        <div class="lg:col-span-5 flex flex-col gap-6">
            <div class="frost-glass rounded-2xl p-6">
                <h2 class="text-xl font-bold mb-4 text-cyan-300 flex items-center gap-2"><span>🎨</span> Styling & Template Engine</h2>
                <div class="space-y-4">
                    <div>
                        <label class="block text-xs font-semibold text-gray-400 mb-2">RESUME TEMPLATE</label>
                        <select id="templateStyle" class="w-full bg-slate-900/90 border border-slate-700 rounded-xl px-4 py-3 text-sm text-gray-200 neon-border outline-none">
                            <option value="modern">Modern Minimalist</option>
                            <option value="executive">Executive Classic</option>
                            <option value="tech">Creative Tech Neon</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-400 mb-2">TYPOGRAPHY FONT</label>
                        <select id="fontFamily" class="w-full bg-slate-900/90 border border-slate-700 rounded-xl px-4 py-3 text-sm text-gray-200 neon-border outline-none">
                            <option value="Helvetica">Helvetica / Sans-Serif</option>
                            <option value="Times-Roman">Times New Roman / Serif</option>
                            <option value="Courier">Courier / Monospace</option>
                        </select>
                    </div>
                </div>
            </div>

            <div class="frost-glass rounded-2xl p-6">
                <h2 class="text-xl font-bold mb-4 text-cyan-300 flex items-center gap-2"><span>📄</span> Job Description & PDF</h2>
                <div class="space-y-4">
                    <textarea id="jobDesc" rows="5" placeholder="Paste target job responsibilities and requirements here..." class="w-full bg-slate-900/90 border border-slate-700 rounded-xl p-4 text-sm text-gray-200 neon-border outline-none resize-none"></textarea>
                    
                    <div class="border-2 border-dashed border-slate-700 hover:border-cyan-500/50 rounded-xl p-6 text-center cursor-pointer transition bg-slate-900/40">
                        <input type="file" id="resumeFile" accept=".pdf" class="hidden" onchange="updateFileName(this)">
                        <label for="resumeFile" class="cursor-pointer flex flex-col items-center">
                            <span class="text-3xl mb-2">❄️</span>
                            <span id="fileNameDisplay" class="text-sm font-semibold text-cyan-400">Upload Resume PDF</span>
                        </label>
                    </div>

                    <button onclick="processMatch()" class="w-full py-4 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 font-extrabold text-slate-950 neon-glow transition">Match & Auto-Rewrite Resume</button>
                </div>
            </div>
        </div>

        <!-- Canvas Output Column -->
        <div class="lg:col-span-7">
            <div class="frost-glass rounded-2xl p-8 h-full flex flex-col justify-between">
                <div>
                    <h2 class="text-2xl font-bold mb-6 text-cyan-300 flex items-center justify-between">
                        <span>✨ AI Tailored Content</span>
                        <span class="text-xs font-normal text-slate-400">Framed Canvas Preview</span>
                    </h2>
                    <div id="outputBullets" class="space-y-4 text-gray-300">
                        <div class="p-6 rounded-xl bg-slate-900/50 border border-slate-800 text-slate-500 text-center">
                            Upload your resume and click process to generate ATS-enhanced bullet points.
                        </div>
                    </div>
                </div>

                <div id="downloadContainer" class="hidden mt-8">
                    <a id="downloadBtn" href="#" class="w-full py-4 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-slate-950 font-bold flex items-center justify-center gap-2 neon-glow transition">
                        <span>📥</span> Download Custom PDF Resume
                    </a>
                </div>
            </div>
        </div>
    </main>

    <!-- IMAGINEART-STYLE SPLIT AUTH MODAL -->
    <div id="authModal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
        <div class="relative w-full max-w-4xl bg-slate-950 border border-cyan-500/30 rounded-3xl overflow-hidden grid grid-cols-1 md:grid-cols-2 shadow-2xl">
            
            <!-- Close Button -->
            <button onclick="closeAuthModal()" class="absolute top-4 right-4 z-20 w-8 h-8 rounded-full bg-slate-800 text-gray-400 hover:text-white flex items-center justify-center">✕</button>

            <!-- Form Side -->
            <div class="p-8 flex flex-col justify-center">
                <div class="mb-6">
                    <h3 id="authTitle" class="text-2xl font-extrabold text-white mb-2">Welcome to DOMA AI</h3>
                    <p class="text-xs text-gray-400">Sign up or login to customize your resume layout.</p>
                </div>

                <!-- OTP Request Form -->
                <div id="authStep1" class="space-y-4">
                    <div>
                        <input type="email" id="authEmail" placeholder="Enter your email" class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-sm text-white neon-border outline-none">
                    </div>
                    <div>
                        <input type="password" id="authPassword" placeholder="Password (8+ chars, Uppercase, Digit, Symbol)" class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-sm text-white neon-border outline-none">
                    </div>
                    <button id="authPrimaryBtn" onclick="handleAuthSubmit()" class="w-full py-3 rounded-xl bg-cyan-400 text-slate-950 font-bold hover:bg-cyan-300 transition">Continue</button>
                    
                    <div class="flex justify-between text-xs text-gray-400 pt-2">
                        <button onclick="toggleAuthMode()" id="toggleAuthBtn" class="hover:text-cyan-400">Need an account? Sign Up</button>
                        <button onclick="triggerForgotPassword()" class="hover:text-cyan-400">Forgot Password?</button>
                    </div>
                </div>

                <!-- OTP Verification Step -->
                <div id="authStep2" class="hidden space-y-4">
                    <p class="text-xs text-cyan-400">We emailed a 6-digit verification code to your inbox.</p>
                    <input type="text" id="otpCode" placeholder="Enter 6-digit Code" class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-sm text-white text-center tracking-widest neon-border outline-none">
                    <button onclick="verifyOTP()" class="w-full py-3 rounded-xl bg-cyan-400 text-slate-950 font-bold hover:bg-cyan-300 transition">Verify Code & Create Account</button>
                </div>
            </div>

            <!-- Graphic Showcase Side -->
            <div class="hidden md:flex flex-col justify-between p-8 bg-gradient-to-br from-cyan-900/40 to-slate-950 border-l border-cyan-500/20 relative overflow-hidden">
                <div class="z-10">
                    <span class="px-3 py-1 rounded-full bg-cyan-500/20 text-cyan-300 text-xs font-semibold">Frost Canvas v2.0</span>
                    <h4 class="text-3xl font-extrabold text-white mt-4 leading-tight">Design Resumes like a Pro.</h4>
                </div>
                <div class="z-10 text-xs text-gray-400">
                    🔒 SOC2 Compliant & Secure Data Processing
                </div>
            </div>

        </div>
    </div>

    <script>
        // --- SNOW CANVAS ANIMATION ---
        const canvas = document.getElementById('snowCanvas');
        const ctx = canvas.getContext('2d');
        let width = canvas.width = window.innerWidth;
        let height = canvas.height = window.innerHeight;

        window.addEventListener('resize', () => {
            width = canvas.width = window.innerWidth;
            height = canvas.height = window.innerHeight;
        });

        const flakes = Array.from({ length: 65 }, () => ({
            x: Math.random() * width,
            y: Math.random() * height,
            radius: Math.random() * 2 + 1,
            speed: Math.random() * 1 + 0.5
        }));

        function drawSnow() {
            ctx.clearRect(0, 0, width, height);
            ctx.fillStyle = 'rgba(0, 242, 254, 0.4)';
            ctx.beginPath();
            flakes.forEach(f => {
                ctx.moveTo(f.x, f.y);
                ctx.arc(f.x, f.y, f.radius, 0, Math.PI * 2);
                f.y += f.speed;
                if (f.y > height) f.y = 0;
            });
            ctx.fill();
            requestAnimationFrame(drawSnow);
        }
        drawSnow();

        // --- AUTH MODAL STATE ---
        let currentAuthMode = 'signup';

        function openAuthModal(mode) {
            currentAuthMode = mode;
            document.getElementById('authModal').classList.remove('hidden');
            document.getElementById('authTitle').innerText = mode === 'signup' ? 'Create Your Account' : 'Log In to DOMA AI';
            document.getElementById('authStep1').classList.remove('hidden');
            document.getElementById('authStep2').classList.add('hidden');
        }

        function closeAuthModal() {
            document.getElementById('authModal').classList.add('hidden');
        }

        function toggleAuthMode() {
            openAuthModal(currentAuthMode === 'signup' ? 'login' : 'signup');
        }

        function updateFileName(input) {
            if (input.files.length > 0) {
                document.getElementById('fileNameDisplay').innerText = input.files[0].name;
            }
        }

        async function handleAuthSubmit() {
            const email = document.getElementById('authEmail').value;
            const password = document.getElementById('authPassword').value;

            if (currentAuthMode === 'signup') {
                const res = await fetch('/api/auth/request-otp', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ email, password })
                });
                const data = await res.json();
                if (res.ok) {
                    document.getElementById('authStep1').classList.add('hidden');
                    document.getElementById('authStep2').classList.remove('hidden');
                } else {
                    alert(data.detail);
                }
            } else {
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ email, password })
                });
                const data = await res.json();
                if (res.ok) {
                    document.getElementById('userBadge').classList.remove('hidden');
                    document.getElementById('coinCount').innerText = data.coins;
                    closeAuthModal();
                } else {
                    alert(data.detail);
                }
            }
        }

        async function verifyOTP() {
            const email = document.getElementById('authEmail').value;
            const otp = document.getElementById('otpCode').value;

            const res = await fetch('/api/auth/verify-otp', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ email, otp })
            });
            const data = await res.json();
            if (res.ok) {
                document.getElementById('userBadge').classList.remove('hidden');
                document.getElementById('coinCount').innerText = data.coins;
                closeAuthModal();
            } else {
                alert(data.detail);
            }
        }

        async function triggerForgotPassword() {
            const email = prompt("Enter your account email address:");
            if (email) {
                const res = await fetch('/api/auth/forgot-password', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ email })
                });
                const data = await res.json();
                alert(data.message || data.detail);
            }
        }

        async function processMatch() {
            const fileInput = document.getElementById('resumeFile');
            const jobDesc = document.getElementById('jobDesc').value;
            const templateStyle = document.getElementById('templateStyle').value;
            const fontFamily = document.getElementById('fontFamily').value;

            if (!fileInput.files[0] || !jobDesc) {
                alert("Please provide both a job description and upload a resume PDF.");
                return;
            }

            const formData = new FormData();
            formData.append('resume', fileInput.files[0]);
            formData.append('job_description', jobDesc);
            formData.append('template_style', templateStyle);
            formData.append('font_family', fontFamily);

            const res = await fetch('/api/match-resume', { method: 'POST', body: formData });
            const data = await res.json();

            if (res.ok) {
                const bulletContainer = document.getElementById('outputBullets');
                bulletContainer.innerHTML = data.bullets.map(b => `<div class="p-4 rounded-xl bg-slate-900/80 border border-cyan-500/30 text-cyan-200">✨ ${b}</div>`).join('');
                
                document.getElementById('downloadBtn').href = data.download_url;
                document.getElementById('downloadContainer').classList.remove('hidden');
            } else {
                alert("Processing failed.");
            }
        }
    </script>
</body>
</html>
    """