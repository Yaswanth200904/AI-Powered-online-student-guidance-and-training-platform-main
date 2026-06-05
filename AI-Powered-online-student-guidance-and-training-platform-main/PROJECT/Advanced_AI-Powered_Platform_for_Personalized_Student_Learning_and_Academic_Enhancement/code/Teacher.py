import os
import time
import json
import requests
import sqlite3
from flask import Flask, request, jsonify, render_template_string, session

app = Flask(__name__)
app.secret_key = os.urandom(24).hex() # Secure key for session management

# --- SQLITE DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('nexus.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            topic TEXT NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            percentage REAL NOT NULL,
            timestamp REAL NOT NULL
        )
    ''')
    # Insert initial mock data if table is empty
    c.execute('SELECT COUNT(*) FROM assessments')
    if c.fetchone()[0] == 0:
        mock_data = [
            ('Alex Johnson', 'Python Basics', 2, 3, 66.7, time.time() - 86400),
            ('Alex Johnson', 'Machine Learning', 1, 3, 33.3, time.time() - 3600),
            ('Sarah Jenkins', 'Quantum Physics', 3, 3, 100.0, time.time() - 7200),
        ]
        c.executemany('''
            INSERT INTO assessments (username, topic, score, total, percentage, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', mock_data)
    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    conn = sqlite3.connect('nexus.db')
    conn.row_factory = sqlite3.Row # This allows us to access columns by name (like dictionaries)
    return conn

# --- CONFIGURATION ---
# REMINDER: Paste your Google Gemini API Key here
API_KEY = "AIzaSyCAZHKWoi2IAgPF9uxbmqflVvD5kxBvwg0" 

# --- GEMINI API HELPERS ---
def call_gemini(prompt, schema=None):
    api_key_clean = API_KEY.strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key_clean}"
    headers = {'Content-Type': 'application/json'}
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {
            "parts": [{"text": "You are a highly professional, empathetic AI tutor and career advisor designed for personalized education. Your output must be well-structured, easy to read, and academically rigorous but accessible."}]
        }
    }
    
    if schema:
        payload["generationConfig"] = {
            "responseMimeType": "application/json",
            "responseSchema": schema
        }

    # Exponential backoff retry logic
    delays = [1, 2, 4, 8, 16]
    for i, delay in enumerate(delays):
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            text_response = data['candidates'][0]['content']['parts'][0]['text']
            
            if schema:
                return json.loads(text_response)
            return text_response
        except Exception as e:
            if i == len(delays) - 1:
                print(f"API Error: {e}")
                return None
            time.sleep(delay)

# --- ROUTES & ENDPOINTS ---

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

# Auth Endpoints
@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    role = data.get('role', 'student')
    
    if not username:
        return jsonify({"error": "Username is required"}), 400
        
    session['user'] = {'username': username, 'role': role}
    return jsonify({"message": "Logged in successfully", "user": session['user']})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.pop('user', None)
    return jsonify({"message": "Logged out successfully"})

@app.route('/api/auth/session', methods=['GET'])
def get_session():
    if 'user' in session:
        return jsonify({"authenticated": True, "user": session['user']})
    return jsonify({"authenticated": False})

# Learning Endpoints
@app.route('/api/quiz', methods=['POST'])
def generate_quiz():
    if 'user' not in session: return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    topic = data.get('topic', 'General Knowledge')
    current_level = data.get('current', 'Beginner')
    time_avail = data.get('time', '15-30 mins')
    
    # Determine number of questions based on available time
    num_questions = 3 # Default for "5-10 mins (Quick)"
    if "15-30" in time_avail:
        num_questions = 5
    elif "1 hour" in time_avail:
        num_questions = 10
    
    prompt = f"""Create a {num_questions}-question multiple-choice diagnostic quiz to accurately assess a student's knowledge on the topic: "{topic}". 
    The student's self-reported current level is "{current_level}". 
    The questions should be appropriately challenging to find their specific knowledge gaps."""
    
    schema = {
        "type": "OBJECT",
        "properties": {
            "questions": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "question": {"type": "STRING"},
                        "options": {
                            "type": "ARRAY", 
                            "items": {"type": "STRING"}
                        },
                        "correctAnswer": {"type": "STRING"}
                    },
                    "required": ["question", "options", "correctAnswer"]
                }
            }
        },
        "required": ["questions"]
    }
    
    result = call_gemini(prompt, schema)
    if result:
        return jsonify(result)
    return jsonify({"error": "Failed to generate assessment. Please try again."}), 500

@app.route('/api/content', methods=['POST'])
def generate_content():
    if 'user' not in session: return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    profile = data.get('profile', {})
    score = data.get('score', 0)
    total = data.get('total', 3)
    
    topic = profile.get('topic', 'General Knowledge')
    current = profile.get('current', 'Beginner')
    target = profile.get('target', 'Intermediate')
    style = profile.get('style', 'Visual')
    time_avail = profile.get('time', '15 mins')
    
    percentage = (score / total) * 100 if total > 0 else 0
    
    # Save to SQLite DB
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO assessments (username, topic, score, total, percentage, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (session['user']['username'], topic, score, total, percentage, time.time()))
    conn.commit()
    conn.close()
    
    prompt = f"""You are generating a personalized learning module for a student about "{topic}".
    User Profile:
    - Self-Assessed Level: {current}
    - Desired Target Level: {target}
    - Preferred Learning Style: {style}
    - Time Available: {time_avail}
    
    Diagnostic Score: They scored {score}/{total} ({percentage}%).
    
    Based on the paper "Advanced AI-Powered Platform for Personalized Student Learning", generate content that directly addresses their knowledge gaps based on this score. Keep it to the {time_avail} time limit.
    """
    
    if percentage <= 50:
        prompt += f"""
        \n[CRITICAL INSTRUCTION]: Because the student scored {percentage}%, they are struggling. 
        Focus heavily on simplifying foundational concepts. Break down complex ideas into simple analogies.
        Additionally, you MUST add a section at the very end formatted EXACTLY as "### Recommended External Resources". 
        Under this section, provide 3 to 4 high-quality links (e.g., Khan Academy, Coursera, YouTube search links, or official documentation) where they can study the absolute basics of {topic}. Format as a bulleted list of Markdown links with brief descriptions.
        """
    else:
        prompt += f"""
        \n[INSTRUCTION]: The student scored well ({percentage}%). Briefly recap the basics and immediately advance to complex concepts, pushing them towards their target level ({target}).
        """
        
    prompt += "\nFormat entirely in clean Markdown (use #, ##, ###, bullet points, bold text). Do not output plain HTML."
    
    result = call_gemini(prompt)
    if result:
        return jsonify({"content": result, "percentage": percentage})
    return jsonify({"error": "Failed to generate learning material"}), 500

@app.route('/api/career', methods=['POST'])
def generate_career_guide():
    if 'user' not in session: return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    age = data.get('age', 'Not specified')
    skills = data.get('skills', 'Not specified')
    interests = data.get('interests', 'Not specified')
    
    prompt = f"""You are an expert, encouraging career counselor. A student is asking for career guidance to help figure out their future.
    Here is their profile:
    - Age/Education Level: {age}
    - Current Skills: {skills}
    - Interests & Passions: {interests}
    
    Based on this profile, provide a structured and highly specific career guide. Include:
    1. 3 to 4 tailored career paths with a brief explanation of why they fit.
    2. Recommended next steps (e.g., specific things to learn, certifications, or types of projects to build).
    3. A brief, realistic industry outlook for these roles.
    
    Format the response entirely in clean Markdown (use ##, ###, bullet points, bold text). Do not output plain HTML.
    """
    
    result = call_gemini(prompt)
    if result:
        return jsonify({"guidance": result})
    return jsonify({"error": "Failed to generate career guidance. Please try again."}), 500

@app.route('/api/history', methods=['GET'])
def get_history():
    if 'user' not in session: return jsonify({"error": "Unauthorized"}), 401
    username = session['user']['username']
    
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT * FROM assessments WHERE username = ? ORDER BY timestamp DESC', 
        (username,)
    ).fetchall()
    conn.close()
    
    user_history = [dict(row) for row in rows]
    return jsonify({"history": user_history})

@app.route('/api/stats', methods=['GET'])
def get_stats():
    if 'user' not in session or session['user']['role'] != 'teacher': 
        return jsonify({"error": "Unauthorized"}), 401
    
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM assessments ORDER BY timestamp DESC').fetchall()
    conn.close()
    
    assessments = [dict(row) for row in rows]
    return jsonify({"assessments": assessments})


# --- HTML/JS/CSS FRONTEND (Single Page App Architecture) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nexus Learning Platform</title>
    <!-- Tailwind CSS -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Tailwind Typography for beautiful Markdown rendering -->
    <script src="https://cdn.tailwindcss.com?plugins=typography"></script>
    <!-- Marked.js for parsing Markdown -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <!-- Lucide Icons -->
    <script src="https://unpkg.com/lucide@latest"></script>
    <!-- Chart.js for Analytics -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        body { font-family: 'Inter', sans-serif; background-color: #f8fafc; }
        .fade-in { animation: fadeIn 0.4s ease-out forwards; }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        /* Custom scrollbar */
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
        
        .glass-card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(226, 232, 240, 0.8);
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        }
    </style>
</head>
<body class="text-slate-800 antialiased min-h-screen flex flex-col">

    <!-- Navbar -->
    <nav class="bg-white border-b border-slate-200 sticky top-0 z-50 shadow-sm">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex justify-between h-16">
                <div class="flex items-center cursor-pointer" onclick="navigate('dashboard')">
                    <div class="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center mr-3 shadow-md">
                        <i data-lucide="book-open" class="text-white w-5 h-5"></i>
                    </div>
                    <span class="font-bold text-xl tracking-tight text-slate-900">Nexus<span class="text-blue-600">Edu</span></span>
                </div>
                
                <div class="flex items-center space-x-6">
                    <button onclick="navigate('how-it-works')" class="text-slate-500 hover:text-blue-600 font-medium text-sm transition-colors hidden sm:block">
                        How it Works
                    </button>
                    
                    <!-- Auth Container -->
                    <div id="nav-auth-container" class="hidden flex items-center gap-4 border-l border-slate-200 pl-6">
                        <div class="flex items-center gap-2">
                            <div class="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-700 font-bold text-sm" id="user-avatar">U</div>
                            <span class="text-sm font-medium text-slate-700 hidden sm:block" id="user-greeting">User</span>
                        </div>
                        <button onclick="logout()" class="text-slate-400 hover:text-red-600 p-2 rounded-lg hover:bg-red-50 transition-colors" title="Logout">
                            <i data-lucide="log-out" class="w-4 h-4"></i>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </nav>

    <!-- Main Content Area -->
    <main class="flex-grow flex flex-col">
        
        <!-- === LOGIN VIEW === -->
        <div id="view-login" class="flex-grow flex items-center justify-center p-6 fade-in hidden">
            <div class="max-w-4xl w-full bg-white rounded-2xl shadow-xl overflow-hidden flex flex-col md:flex-row border border-slate-100">
                <!-- Graphic Side -->
                <div class="md:w-5/12 bg-blue-600 p-10 text-white flex flex-col justify-center relative overflow-hidden">
                    <div class="absolute -top-24 -right-24 w-64 h-64 bg-blue-500 rounded-full blur-3xl opacity-50"></div>
                    <div class="absolute -bottom-24 -left-24 w-64 h-64 bg-blue-700 rounded-full blur-3xl opacity-50"></div>
                    <div class="relative z-10">
                        <h2 class="text-3xl font-bold mb-4 leading-tight">Personalized Learning, Powered by AI.</h2>
                        <p class="text-blue-100 mb-8">Access custom-tailored curriculum dynamically generated to bridge your specific knowledge gaps.</p>
                        <ul class="space-y-3">
                            <li class="flex items-center gap-3"><i data-lucide="check-circle-2" class="text-blue-300 w-5 h-5"></i> Adaptive Assessments</li>
                            <li class="flex items-center gap-3"><i data-lucide="check-circle-2" class="text-blue-300 w-5 h-5"></i> Targeted Content Generation</li>
                            <li class="flex items-center gap-3"><i data-lucide="check-circle-2" class="text-blue-300 w-5 h-5"></i> AI Career Navigation</li>
                        </ul>
                    </div>
                </div>
                <!-- Form Side -->
                <div class="md:w-7/12 p-10 lg:p-14 flex flex-col justify-center bg-white">
                    <h3 class="text-2xl font-bold text-slate-900 mb-2">Welcome Back</h3>
                    <p class="text-slate-500 mb-8 text-sm">Please sign in to your account to continue.</p>
                    
                    <form onsubmit="handleLogin(event)" class="space-y-5">
                        <div id="login-error" class="hidden bg-red-50 text-red-600 text-sm p-3 rounded-lg border border-red-100"></div>
                        <div>
                            <label class="block text-sm font-medium text-slate-700 mb-1">Username / Full Name</label>
                            <input type="text" id="login-username" required placeholder="e.g., Alex Johnson" 
                                class="w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-blue-600 focus:border-blue-600 outline-none transition-all">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-slate-700 mb-1">Role</label>
                            <select id="login-role" class="w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-blue-600 focus:border-blue-600 outline-none bg-white transition-all">
                                <option value="student">Student</option>
                                <option value="teacher">Teacher / Administrator</option>
                            </select>
                        </div>
                        <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 rounded-lg transition-colors shadow-sm flex justify-center items-center gap-2">
                            Sign In <i data-lucide="arrow-right" class="w-4 h-4"></i>
                        </button>
                    </form>
                </div>
            </div>
        </div>

        <!-- === DASHBOARD VIEW === -->
        <div id="view-dashboard" class="max-w-6xl mx-auto w-full p-6 py-10 fade-in hidden">
            <div class="flex flex-col md:flex-row justify-between items-start md:items-center mb-10 gap-4">
                <div>
                    <h1 class="text-3xl font-bold text-slate-900">Student Dashboard</h1>
                    <p class="text-slate-500 mt-1">Track your progress and start new learning journeys.</p>
                </div>
                <div class="flex flex-wrap gap-3">
                    <button onclick="navigate('career-guide')" class="bg-purple-100 hover:bg-purple-200 text-purple-700 px-6 py-3 rounded-xl font-medium shadow-sm transition-all flex items-center gap-2 transform hover:-translate-y-0.5">
                        <i data-lucide="compass" class="w-5 h-5"></i> Career Guide
                    </button>
                    <button onclick="navigate('learning-flow')" class="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-xl font-medium shadow-md transition-all flex items-center gap-2 hover:shadow-lg transform hover:-translate-y-0.5">
                        <i data-lucide="plus-circle" class="w-5 h-5"></i> Start New Topic
                    </button>
                </div>
            </div>

            <!-- Stats Row -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10">
                <div class="glass-card rounded-2xl p-6">
                    <div class="flex justify-between items-start">
                        <div>
                            <p class="text-sm font-medium text-slate-500 mb-1">Modules Completed</p>
                            <h3 id="stat-modules" class="text-3xl font-bold text-slate-900">0</h3>
                        </div>
                        <div class="p-3 bg-emerald-100 rounded-lg"><i data-lucide="check-square" class="w-6 h-6 text-emerald-600"></i></div>
                    </div>
                </div>
                <div class="glass-card rounded-2xl p-6">
                    <div class="flex justify-between items-start">
                        <div>
                            <p class="text-sm font-medium text-slate-500 mb-1">Avg. Assessment Score</p>
                            <h3 id="stat-avg" class="text-3xl font-bold text-slate-900">0%</h3>
                        </div>
                        <div class="p-3 bg-blue-100 rounded-lg"><i data-lucide="target" class="w-6 h-6 text-blue-600"></i></div>
                    </div>
                </div>
                <div class="glass-card rounded-2xl p-6">
                    <div class="flex justify-between items-start">
                        <div>
                            <p class="text-sm font-medium text-slate-500 mb-1">Recent Improvement</p>
                            <h3 id="stat-improvement" class="text-3xl font-bold text-slate-900">--</h3>
                        </div>
                        <div class="p-3 bg-orange-100 rounded-lg"><i data-lucide="trending-up" class="w-6 h-6 text-orange-600"></i></div>
                    </div>
                </div>
            </div>

            <h2 class="text-xl font-bold text-slate-800 mb-6">Exam History & Performance</h2>
            <div class="glass-card rounded-2xl overflow-hidden">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="bg-slate-50 border-b border-slate-200 text-slate-500 text-sm">
                            <th class="p-4 font-medium">Topic</th>
                            <th class="p-4 font-medium">Date</th>
                            <th class="p-4 font-medium">Diagnostic Score</th>
                            <th class="p-4 font-medium">Status</th>
                        </tr>
                    </thead>
                    <tbody id="history-table-body">
                        <!-- Dynamic Content Loaded via JS -->
                    </tbody>
                </table>
            </div>
        </div>

        <!-- === CAREER GUIDE VIEW === -->
        <div id="view-career-guide" class="max-w-4xl mx-auto w-full p-6 py-10 fade-in hidden">
            
            <button onclick="navigate('dashboard')" class="text-slate-400 hover:text-slate-600 flex items-center gap-2 mb-6 font-medium text-sm transition-colors">
                <i data-lucide="arrow-left" class="w-4 h-4"></i> Return to Dashboard
            </button>

            <div class="glass-card rounded-2xl shadow-sm overflow-hidden p-8">
                <div class="flex items-center gap-4 mb-6 pb-6 border-b border-slate-100">
                    <div class="w-12 h-12 bg-purple-100 text-purple-600 rounded-xl flex items-center justify-center shrink-0">
                        <i data-lucide="compass" class="w-6 h-6"></i>
                    </div>
                    <div>
                        <h2 class="text-2xl font-bold text-slate-900">AI Career Navigator</h2>
                        <p class="text-slate-500 text-sm">Discover potential career paths tailored to your unique profile.</p>
                    </div>
                </div>

                <!-- Input Form -->
                <div id="career-form" class="space-y-6">
                    <div class="grid md:grid-cols-2 gap-6">
                        <div>
                            <label class="block text-sm font-semibold text-slate-700 mb-2">Age / Education Level</label>
                            <input id="cg-age" type="text" placeholder="e.g., 20, High School Senior" 
                                class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-purple-600 focus:bg-white transition-all outline-none text-slate-800"/>
                        </div>
                        <div>
                            <label class="block text-sm font-semibold text-slate-700 mb-2">Current Skills</label>
                            <input id="cg-skills" type="text" placeholder="e.g., Python, Public Speaking, Art" 
                                class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-purple-600 focus:bg-white transition-all outline-none text-slate-800"/>
                        </div>
                    </div>
                    <div>
                        <label class="block text-sm font-semibold text-slate-700 mb-2">Interests & Passions</label>
                        <textarea id="cg-interests" rows="3" placeholder="e.g., I love building apps, helping people, and solving puzzles..." 
                            class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-purple-600 focus:bg-white transition-all outline-none text-slate-800"></textarea>
                    </div>

                    <button onclick="requestCareerGuide()" class="w-full bg-purple-600 hover:bg-purple-700 text-white font-semibold py-4 rounded-xl transition-all shadow-md hover:shadow-lg flex justify-center items-center gap-2 mt-4">
                        Map My Career Path <i data-lucide="map" class="w-4 h-4"></i>
                    </button>
                </div>

                <!-- Results Output -->
                <div id="career-results" class="hidden mt-8 pt-8 border-t border-slate-100">
                    <div id="career-content" class="prose prose-slate prose-purple max-w-none prose-headings:font-bold prose-h1:text-3xl prose-a:text-purple-600 hover:prose-a:text-purple-500"></div>
                    
                    <div class="mt-8">
                        <button onclick="resetCareerGuide()" class="bg-slate-100 hover:bg-slate-200 text-slate-800 font-semibold py-3 px-6 rounded-xl transition-colors">
                            Explore Another Path
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- === TEACHER DASHBOARD VIEW === -->
        <div id="view-teacher-dashboard" class="max-w-6xl mx-auto w-full p-6 py-10 fade-in hidden">
            <div class="flex flex-col md:flex-row justify-between items-start md:items-center mb-10 gap-4">
                <div>
                    <h1 class="text-3xl font-bold text-slate-900">Teacher Analytics</h1>
                    <p class="text-slate-500 mt-1">Monitor cohort performance and identify knowledge gaps.</p>
                </div>
            </div>

            <!-- Stats Row -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div class="glass-card rounded-2xl p-6 border-l-4 border-l-blue-500">
                    <p class="text-sm font-medium text-slate-500 mb-1">Total Assessments</p>
                    <h3 id="t-stat-total" class="text-3xl font-bold text-slate-900">0</h3>
                </div>
                <div class="glass-card rounded-2xl p-6 border-l-4 border-l-emerald-500">
                    <p class="text-sm font-medium text-slate-500 mb-1">Cohort Average</p>
                    <h3 id="t-stat-avg" class="text-3xl font-bold text-slate-900">0%</h3>
                </div>
                <div class="glass-card rounded-2xl p-6 border-l-4 border-l-red-500">
                    <p class="text-sm font-medium text-slate-500 mb-1">Struggling Students (< 50%)</p>
                    <h3 id="t-stat-struggling" class="text-3xl font-bold text-slate-900">0</h3>
                </div>
            </div>

            <!-- Charts Row -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
                <div class="glass-card rounded-2xl p-6">
                    <h3 class="font-bold text-slate-800 mb-4">Average Score by Topic</h3>
                    <canvas id="topicChart" height="200"></canvas>
                </div>
                <div class="glass-card rounded-2xl p-6">
                    <h3 class="font-bold text-slate-800 mb-4">Recent Assessment Timeline</h3>
                    <canvas id="timelineChart" height="200"></canvas>
                </div>
            </div>

            <h2 class="text-xl font-bold text-slate-800 mb-6">Recent Student Activity</h2>
            <div class="glass-card rounded-2xl overflow-hidden">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="bg-slate-50 border-b border-slate-200 text-slate-500 text-sm">
                            <th class="p-4 font-medium">Student</th>
                            <th class="p-4 font-medium">Topic</th>
                            <th class="p-4 font-medium">Score</th>
                            <th class="p-4 font-medium">Action Needed</th>
                        </tr>
                    </thead>
                    <tbody id="teacher-table-body">
                        <!-- Dynamic Content Loaded via JS -->
                    </tbody>
                </table>
            </div>
        </div>

        <!-- === HOW IT WORKS VIEW === -->
        <div id="view-how-it-works" class="max-w-5xl mx-auto w-full p-6 py-12 fade-in hidden">
            <div class="text-center mb-16">
                <h1 class="text-4xl font-extrabold text-slate-900 mb-4">The Science Behind NexusEdu</h1>
                <p class="text-xl text-slate-500 max-w-2xl mx-auto">Based on advanced research in AI-driven pedagogy, our platform customizes every learning interaction.</p>
            </div>

            <div class="space-y-12 relative before:absolute before:inset-0 before:ml-5 before:-translate-x-px md:before:mx-auto md:before:translate-x-0 before:h-full before:w-0.5 before:bg-gradient-to-b before:from-transparent before:via-blue-300 before:to-transparent">
                <!-- Step 1 -->
                <div class="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group is-active">
                    <div class="flex items-center justify-center w-10 h-10 rounded-full border border-white bg-blue-100 text-blue-600 shadow shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2 z-10">
                        <i data-lucide="user-circle" class="w-5 h-5"></i>
                    </div>
                    <div class="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] glass-card p-6 rounded-2xl shadow-sm">
                        <div class="flex items-center justify-between mb-2">
                            <h3 class="font-bold text-slate-900 text-lg">1. User Profiling</h3>
                        </div>
                        <p class="text-slate-600">We capture your current knowledge, desired goals, time constraints, and learning styles to establish a baseline.</p>
                    </div>
                </div>
                <!-- Step 2 -->
                <div class="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group is-active">
                    <div class="flex items-center justify-center w-10 h-10 rounded-full border border-white bg-indigo-100 text-indigo-600 shadow shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2 z-10">
                        <i data-lucide="help-circle" class="w-5 h-5"></i>
                    </div>
                    <div class="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] glass-card p-6 rounded-2xl shadow-sm">
                        <h3 class="font-bold text-slate-900 text-lg mb-2">2. Adaptive Quiz Generation</h3>
                        <p class="text-slate-600">Using LangChain & Gemini AI, a diagnostic quiz is dynamically generated to accurately map your specific knowledge gaps.</p>
                    </div>
                </div>
                <!-- Step 3 -->
                <div class="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group is-active">
                    <div class="flex items-center justify-center w-10 h-10 rounded-full border border-white bg-purple-100 text-purple-600 shadow shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2 z-10">
                        <i data-lucide="brain-circuit" class="w-5 h-5"></i>
                    </div>
                    <div class="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] glass-card p-6 rounded-2xl shadow-sm">
                        <h3 class="font-bold text-slate-900 text-lg mb-2">3. Response Analysis</h3>
                        <p class="text-slate-600">Rigorous evaluation of your answers identifies exactly what you struggle with, shifting focus away from what you already know.</p>
                    </div>
                </div>
                <!-- Step 4 -->
                <div class="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group is-active">
                    <div class="flex items-center justify-center w-10 h-10 rounded-full border border-white bg-emerald-100 text-emerald-600 shadow shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2 z-10">
                        <i data-lucide="book-text" class="w-5 h-5"></i>
                    </div>
                    <div class="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] glass-card p-6 rounded-2xl shadow-sm">
                        <h3 class="font-bold text-slate-900 text-lg mb-2">4. Personalized Content Creation</h3>
                        <p class="text-slate-600">The LLM generates tailored explanations, summaries, and (if you're struggling) strict referral links to top-tier external resources.</p>
                    </div>
                </div>
            </div>
            
            <div class="text-center mt-16">
                <button onclick="navigate('dashboard')" class="text-blue-600 hover:text-blue-800 font-semibold flex items-center justify-center mx-auto gap-2">
                    <i data-lucide="arrow-left" class="w-4 h-4"></i> Back to Dashboard
                </button>
            </div>
        </div>

        <!-- === LEARNING FLOW VIEW (The Core App) === -->
        <div id="view-learning-flow" class="max-w-4xl mx-auto w-full p-6 py-10 fade-in hidden">
            
            <button onclick="navigate('dashboard')" class="text-slate-400 hover:text-slate-600 flex items-center gap-2 mb-6 font-medium text-sm transition-colors">
                <i data-lucide="arrow-left" class="w-4 h-4"></i> Return to Dashboard
            </button>

            <!-- Loading Overlay -->
            <div id="loading-overlay" class="hidden fixed inset-0 bg-white/80 backdrop-blur-sm z-50 flex flex-col items-center justify-center">
                <div class="animate-spin rounded-full h-16 w-16 border-b-4 border-blue-600 mb-4"></div>
                <h3 id="loading-text" class="text-xl font-bold text-slate-800">Processing...</h3>
                <p class="text-slate-500 mt-2">AI engines are analyzing your request.</p>
            </div>

            <!-- Flow Container -->
            <div class="glass-card rounded-2xl shadow-sm overflow-hidden">
                
                <!-- 1. Profile Form -->
                <div id="step-profile" class="p-8 fade-in">
                    <div class="flex items-center gap-4 mb-6 pb-6 border-b border-slate-100">
                        <div class="w-12 h-12 bg-blue-100 text-blue-600 rounded-xl flex items-center justify-center shrink-0">
                            <i data-lucide="settings-2" class="w-6 h-6"></i>
                        </div>
                        <div>
                            <h2 class="text-2xl font-bold text-slate-900">Define Your Objective</h2>
                            <p class="text-slate-500 text-sm">Step 1: Set up your learning parameters.</p>
                        </div>
                    </div>

                    <div id="error-msg" class="hidden mb-6 bg-red-50 text-red-600 p-4 rounded-lg text-sm border border-red-100 flex items-center gap-2"></div>

                    <div class="space-y-6">
                        <div>
                            <label class="block text-sm font-semibold text-slate-700 mb-2">What do you want to learn?</label>
                            <input id="prof-topic" type="text" placeholder="e.g., Photosynthesis, React Hooks, World War II..." 
                                class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-600 focus:bg-white transition-all outline-none text-slate-800"/>
                        </div>
                        
                        <div class="grid md:grid-cols-2 gap-6">
                            <div>
                                <label class="block text-sm font-semibold text-slate-700 mb-2">Current Understanding</label>
                                <select id="prof-current" class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-600 focus:bg-white transition-all outline-none">
                                    <option>Absolute Beginner</option>
                                    <option>Beginner</option>
                                    <option>Intermediate</option>
                                    <option>Advanced</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-sm font-semibold text-slate-700 mb-2">Target Goal</label>
                                <select id="prof-target" class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-600 focus:bg-white transition-all outline-none">
                                    <option>Beginner (Basics)</option>
                                    <option>Intermediate (Working Knowledge)</option>
                                    <option>Advanced (Mastery)</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-sm font-semibold text-slate-700 mb-2">Learning Style</label>
                                <select id="prof-style" class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-600 focus:bg-white transition-all outline-none">
                                    <option>Visual (Diagrams, summaries)</option>
                                    <option>Analytical (Deep theory, math)</option>
                                    <option>Practical (Real-world usage)</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-sm font-semibold text-slate-700 mb-2">Time Available</label>
                                <select id="prof-time" class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-600 focus:bg-white transition-all outline-none">
                                    <option>5-10 mins (Quick)</option>
                                    <option>15-30 mins (Standard)</option>
                                    <option>1 hour+ (Deep Dive)</option>
                                </select>
                            </div>
                        </div>

                        <button onclick="requestQuiz()" class="w-full bg-slate-900 hover:bg-black text-white font-semibold py-4 rounded-xl transition-all shadow-md hover:shadow-lg flex justify-center items-center gap-2 mt-4">
                            Generate Diagnostic Assessment <i data-lucide="arrow-right" class="w-4 h-4"></i>
                        </button>
                    </div>
                </div>

                <!-- 2. Quiz Form -->
                <div id="step-quiz" class="hidden p-8 fade-in">
                    <div class="flex items-center justify-between mb-6 pb-6 border-b border-slate-100">
                        <div>
                            <h2 class="text-2xl font-bold text-slate-900">Knowledge Diagnostic</h2>
                            <p class="text-slate-500 text-sm mt-1">Answer these questions to help AI find your gaps.</p>
                        </div>
                        <span id="quiz-topic-label" class="bg-blue-50 text-blue-700 px-4 py-1.5 rounded-full text-sm font-bold border border-blue-200"></span>
                    </div>

                    <div id="quiz-container" class="space-y-8 mb-8"></div>

                    <button id="btn-submit-quiz" onclick="submitQuiz()" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-4 rounded-xl transition-all shadow-md opacity-50 cursor-not-allowed flex justify-center items-center gap-2" disabled>
                        Analyze & Generate Curriculum <i data-lucide="sparkles" class="w-4 h-4"></i>
                    </button>
                </div>

                <!-- 3. Generated Content -->
                <div id="step-content" class="hidden fade-in">
                    <!-- Score Header -->
                    <div class="bg-slate-900 text-white p-8">
                        <div class="flex items-center justify-between">
                            <div>
                                <p class="text-blue-400 text-sm font-bold uppercase tracking-wider mb-2">Diagnostic Complete</p>
                                <h3 id="result-text" class="text-3xl font-bold mb-2"></h3>
                                <p id="result-subtext" class="text-slate-300"></p>
                            </div>
                            <div class="relative">
                                <svg class="w-24 h-24 transform -rotate-90">
                                    <circle cx="48" cy="48" r="36" stroke="currentColor" stroke-width="8" fill="transparent" class="text-slate-700" />
                                    <circle id="score-circle" cx="48" cy="48" r="36" stroke="currentColor" stroke-width="8" fill="transparent" stroke-dasharray="226.2" stroke-dashoffset="0" class="text-blue-500 transition-all duration-1000 ease-out" />
                                </svg>
                                <div class="absolute inset-0 flex items-center justify-center">
                                    <span id="result-score" class="text-xl font-bold"></span>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Markdown Output -->
                    <div class="p-8 bg-white">
                        <div id="lesson-content" class="prose prose-slate prose-blue max-w-none prose-headings:font-bold prose-h1:text-3xl prose-a:text-blue-600 hover:prose-a:text-blue-500 prose-img:rounded-xl"></div>
                        
                        <div class="mt-12 pt-8 border-t border-slate-100">
                            <button onclick="navigate('dashboard')" class="bg-slate-100 hover:bg-slate-200 text-slate-800 font-semibold py-3 px-6 rounded-xl transition-colors">
                                Complete & Return
                            </button>
                        </div>
                    </div>
                </div>

            </div>
        </div>
    </main>

    <!-- App Logic Scripts -->
    <script>
        // Initialize Lucide Icons
        lucide.createIcons();

        // State Management
        let appState = {
            user: null,
            profile: {},
            quizData: [],
            userAnswers: {}
        };
        
        let charts = {}; // Store Chart.js instances

        // --- Routing & Initialization ---
        async function initApp() {
            try {
                const res = await fetch('/api/auth/session');
                const data = await res.json();
                if(data.authenticated) {
                    appState.user = data.user;
                    updateNavAuth();
                    navigate(appState.user.role === 'teacher' ? 'teacher-dashboard' : 'dashboard');
                } else {
                    navigate('login');
                }
            } catch (e) {
                navigate('login');
            }
        }

        function updateNavAuth() {
            if(appState.user) {
                document.getElementById('nav-auth-container').classList.remove('hidden');
                document.getElementById('nav-auth-container').classList.add('flex');
                document.getElementById('user-greeting').textContent = appState.user.username;
                document.getElementById('user-avatar').textContent = appState.user.username.charAt(0).toUpperCase();
            } else {
                document.getElementById('nav-auth-container').classList.add('hidden');
                document.getElementById('nav-auth-container').classList.remove('flex');
            }
        }

        function navigate(viewName) {
            ['view-login', 'view-dashboard', 'view-teacher-dashboard', 'view-how-it-works', 'view-learning-flow', 'view-career-guide'].forEach(id => {
                const el = document.getElementById(id);
                if(el) el.classList.add('hidden');
            });
            
            // Intercept generic 'dashboard' routing based on role
            if(viewName === 'dashboard' && appState.user && appState.user.role === 'teacher') {
                viewName = 'teacher-dashboard';
            }
            
            const targetView = document.getElementById(`view-${viewName}`);
            if(targetView) targetView.classList.remove('hidden');
            
            if(viewName === 'learning-flow') {
                showLearningStep('profile');
                document.getElementById('prof-topic').value = '';
            } else if (viewName === 'dashboard') {
                loadStudentDashboard();
            } else if (viewName === 'teacher-dashboard') {
                loadTeacherDashboard();
            }
        }

        // --- Dashboard Data Loaders ---
        async function loadStudentDashboard() {
            try {
                const res = await fetch('/api/history');
                const data = await res.json();
                const history = data.history || [];
                
                document.getElementById('stat-modules').textContent = history.length;
                
                if(history.length > 0) {
                    const avg = history.reduce((sum, item) => sum + item.percentage, 0) / history.length;
                    document.getElementById('stat-avg').textContent = Math.round(avg) + '%';
                    
                    if(history.length > 1) {
                        const latest = history[0].percentage;
                        const previous = history[1].percentage;
                        const diff = Math.round(latest - previous);
                        const impEl = document.getElementById('stat-improvement');
                        if(diff > 0) {
                            impEl.textContent = `+${diff}%`;
                            impEl.className = "text-3xl font-bold text-emerald-600";
                        } else if (diff < 0) {
                            impEl.textContent = `${diff}%`;
                            impEl.className = "text-3xl font-bold text-red-600";
                        } else {
                            impEl.textContent = `0%`;
                            impEl.className = "text-3xl font-bold text-slate-600";
                        }
                    } else {
                        document.getElementById('stat-improvement').textContent = '--';
                        document.getElementById('stat-improvement').className = "text-3xl font-bold text-slate-900";
                    }
                }
                
                const tbody = document.getElementById('history-table-body');
                tbody.innerHTML = '';
                history.forEach(item => {
                    const date = new Date(item.timestamp * 1000).toLocaleDateString();
                    const statusClass = item.percentage >= 80 ? 'bg-emerald-100 text-emerald-700' : 
                                      (item.percentage <= 50 ? 'bg-amber-100 text-amber-700' : 'bg-blue-100 text-blue-700');
                    const statusText = item.percentage >= 80 ? 'Mastered' : 
                                     (item.percentage <= 50 ? 'Needs Review' : 'Completed');
                    
                    tbody.innerHTML += `
                        <tr class="border-b border-slate-100 hover:bg-slate-50">
                            <td class="p-4 text-slate-900 font-medium">${item.topic}</td>
                            <td class="p-4 text-slate-500">${date}</td>
                            <td class="p-4 text-slate-600 font-bold">${Math.round(item.percentage)}%</td>
                            <td class="p-4"><span class="px-2.5 py-1 ${statusClass} text-xs font-semibold rounded-full">${statusText}</span></td>
                        </tr>
                    `;
                });
            } catch (e) {
                console.error('Failed to load history', e);
            }
        }

        async function loadTeacherDashboard() {
            try {
                const res = await fetch('/api/stats');
                const data = await res.json();
                const assessments = data.assessments || [];
                
                document.getElementById('t-stat-total').textContent = assessments.length;
                
                let strugglingCount = 0;
                let sum = 0;
                let topicMap = {};
                
                const tbody = document.getElementById('teacher-table-body');
                tbody.innerHTML = '';
                
                assessments.forEach((item, index) => {
                    sum += item.percentage;
                    if(item.percentage <= 50) strugglingCount++;
                    
                    if(!topicMap[item.topic]) topicMap[item.topic] = { sum: 0, count: 0 };
                    topicMap[item.topic].sum += item.percentage;
                    topicMap[item.topic].count += 1;
                    
                    if(index < 10) { // Show top 10 recent
                        const statusClass = item.percentage <= 50 ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-700';
                        const statusText = item.percentage <= 50 ? 'Intervention Recommended' : 'None';
                        tbody.innerHTML += `
                            <tr class="border-b border-slate-100 hover:bg-slate-50">
                                <td class="p-4 text-slate-900 font-medium">${item.username}</td>
                                <td class="p-4 text-slate-600">${item.topic}</td>
                                <td class="p-4 text-slate-900 font-bold">${Math.round(item.percentage)}%</td>
                                <td class="p-4"><span class="px-2.5 py-1 ${statusClass} text-xs font-semibold rounded-full">${statusText}</span></td>
                            </tr>
                        `;
                    }
                });
                
                if(assessments.length > 0) {
                    document.getElementById('t-stat-avg').textContent = Math.round(sum / assessments.length) + '%';
                }
                document.getElementById('t-stat-struggling').textContent = strugglingCount;
                
                // Render Charts
                renderTeacherCharts(assessments, topicMap);
                
            } catch (e) {
                console.error('Failed to load stats', e);
            }
        }

        function renderTeacherCharts(assessments, topicMap) {
            const topicLabels = Object.keys(topicMap);
            const topicAverages = topicLabels.map(t => Math.round(topicMap[t].sum / topicMap[t].count));
            
            if(charts.topicChart) charts.topicChart.destroy();
            const ctx1 = document.getElementById('topicChart').getContext('2d');
            charts.topicChart = new Chart(ctx1, {
                type: 'bar',
                data: {
                    labels: topicLabels,
                    datasets: [{
                        label: 'Average Score (%)',
                        data: topicAverages,
                        backgroundColor: 'rgba(59, 130, 246, 0.5)',
                        borderColor: 'rgb(59, 130, 246)',
                        borderWidth: 1,
                        borderRadius: 4
                    }]
                },
                options: { scales: { y: { beginAtZero: true, max: 100 } } }
            });

            // Timeline chart (last 10 assessments)
            const recent = [...assessments].reverse().slice(-10);
            if(charts.timelineChart) charts.timelineChart.destroy();
            const ctx2 = document.getElementById('timelineChart').getContext('2d');
            charts.timelineChart = new Chart(ctx2, {
                type: 'line',
                data: {
                    labels: recent.map(a => new Date(a.timestamp * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})),
                    datasets: [{
                        label: 'Score Trend (%)',
                        data: recent.map(a => a.percentage),
                        borderColor: 'rgb(16, 185, 129)',
                        tension: 0.3,
                        fill: false
                    }]
                },
                options: { scales: { y: { beginAtZero: true, max: 100 } } }
            });
        }

        // --- Authentication ---
        async function handleLogin(e) {
            e.preventDefault();
            const username = document.getElementById('login-username').value;
            const role = document.getElementById('login-role').value;
            const errDiv = document.getElementById('login-error');
            
            try {
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username, role})
                });
                const data = await res.json();
                
                if(res.ok) {
                    appState.user = data.user;
                    updateNavAuth();
                    errDiv.classList.add('hidden');
                    navigate(appState.user.role === 'teacher' ? 'teacher-dashboard' : 'dashboard');
                } else {
                    errDiv.textContent = data.error;
                    errDiv.classList.remove('hidden');
                }
            } catch (err) {
                errDiv.textContent = "Network error. Please try again.";
                errDiv.classList.remove('hidden');
            }
        }

        async function logout() {
            await fetch('/api/auth/logout', { method: 'POST' });
            appState.user = null;
            updateNavAuth();
            navigate('login');
        }

        // --- UI Helpers ---
        function toggleLoading(show, text="Processing...") {
            const overlay = document.getElementById('loading-overlay');
            if (overlay) {
                document.getElementById('loading-text').textContent = text;
                if(show) overlay.classList.remove('hidden');
                else overlay.classList.add('hidden');
            }
        }

        function showError(msg) {
            alert(msg);
        }

        // --- Career Guide Logic ---
        async function requestCareerGuide() {
            const age = document.getElementById('cg-age').value.trim();
            const skills = document.getElementById('cg-skills').value.trim();
            const interests = document.getElementById('cg-interests').value.trim();

            if(!skills || !interests) return showError("Please provide at least some skills and interests so the AI can help you.");

            toggleLoading(true, "Consulting AI Career Advisor...");

            try {
                const res = await fetch('/api/career', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({age, skills, interests})
                });
                const data = await res.json();
                
                if(data.error) throw new Error(data.error);
                
                // Switch UI from Form to Results
                document.getElementById('career-form').classList.add('hidden');
                document.getElementById('career-results').classList.remove('hidden');
                
                // Render Markdown content
                document.getElementById('career-content').innerHTML = marked.parse(data.guidance);
                
            } catch (err) {
                showError("Failed to generate career guidance. Please try again.");
            } finally {
                toggleLoading(false);
            }
        }

        function resetCareerGuide() {
            document.getElementById('career-form').classList.remove('hidden');
            document.getElementById('career-results').classList.add('hidden');
            document.getElementById('cg-age').value = '';
            document.getElementById('cg-skills').value = '';
            document.getElementById('cg-interests').value = '';
        }

        // --- Learning Flow ---
        function showLearningStep(stepName) {
            ['step-profile', 'step-quiz', 'step-content'].forEach(id => {
                document.getElementById(id).classList.add('hidden');
            });
            document.getElementById(`step-${stepName}`).classList.remove('hidden');
        }

        // 1. Request the quiz from the backend
        async function requestQuiz() {
            const topic = document.getElementById('prof-topic').value.trim();
            if(!topic) return showError("Please enter a topic you wish to learn.");

            appState.profile = {
                topic: topic,
                current: document.getElementById('prof-current').value,
                target: document.getElementById('prof-target').value,
                style: document.getElementById('prof-style').value,
                time: document.getElementById('prof-time').value
            };

            toggleLoading(true, "Generating Diagnostic Assessment...");
            appState.userAnswers = {};

            try {
                const res = await fetch('/api/quiz', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        topic: appState.profile.topic, 
                        current: appState.profile.current,
                        time: appState.profile.time
                    })
                });
                const data = await res.json();
                
                if(data.error) throw new Error(data.error);
                
                // Render the quiz and move to the quiz step
                appState.quizData = data.questions;
                renderQuiz();
                showLearningStep('quiz');
                
            } catch (err) {
                console.error(err);
                showError("Failed to generate quiz. Please try again.");
                showLearningStep('profile');
            } finally {
                toggleLoading(false);
            }
        }

        // 2. Render the generated quiz to the screen
        function renderQuiz() {
            document.getElementById('quiz-topic-label').textContent = appState.profile.topic;
            const container = document.getElementById('quiz-container');
            container.innerHTML = '';

            appState.quizData.forEach((q, index) => {
                const qDiv = document.createElement('div');
                qDiv.className = 'p-6 bg-slate-50 rounded-xl border border-slate-200 mb-4';

                let optionsHtml = '';
                q.options.forEach((opt) => {
                    const safeOpt = opt.replace(/"/g, '&quot;');
                    optionsHtml += `
                        <label class="flex items-center p-3 mt-3 border border-slate-200 rounded-lg cursor-pointer hover:bg-blue-50 transition-colors bg-white">
                            <input type="radio" name="q${index}" value="${safeOpt}" onchange="selectAnswer(${index}, this.value)" class="w-4 h-4 text-blue-600 border-slate-300 focus:ring-blue-600">
                            <span class="ml-3 text-slate-700">${opt}</span>
                        </label>
                    `;
                });

                qDiv.innerHTML = `
                    <h3 class="font-bold text-slate-800 mb-2">Q${index + 1}: ${q.question}</h3>
                    <div class="space-y-2">${optionsHtml}</div>
                `;
                container.appendChild(qDiv);
            });

            const btn = document.getElementById('btn-submit-quiz');
            btn.disabled = true;
            btn.classList.add('opacity-50', 'cursor-not-allowed');
        }

        // 3. Handle when the user clicks an answer
        function selectAnswer(qIndex, answer) {
            appState.userAnswers[qIndex] = answer;
            const btn = document.getElementById('btn-submit-quiz');
            
            // Check if all questions are answered
            if (Object.keys(appState.userAnswers).length === appState.quizData.length) {
                btn.disabled = false;
                btn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        }

        // 4. Calculate score and submit to generate the lesson
        async function submitQuiz() {
            toggleLoading(true, "Analyzing Results & Generating Content...");

            let score = 0;
            appState.quizData.forEach((q, index) => {
                if (appState.userAnswers[index] === q.correctAnswer) {
                    score++;
                }
            });

            try {
                const res = await fetch('/api/content', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        profile: appState.profile,
                        score: score,
                        total: appState.quizData.length
                    })
                });
                const data = await res.json();

                if(data.error) throw new Error(data.error);

                // Update Results UI
                document.getElementById('result-text').textContent = `You scored ${score} out of ${appState.quizData.length}`;
                document.getElementById('result-score').textContent = `${Math.round(data.percentage)}%`;

                // Animate SVG Circle
                const circle = document.getElementById('score-circle');
                const offset = 226.2 - (226.2 * data.percentage) / 100;
                circle.style.strokeDashoffset = offset;

                if(data.percentage <= 50) {
                    document.getElementById('result-subtext').textContent = "We identified some foundational gaps. We've simplified the material and included recommended external resources below.";
                    circle.classList.replace('text-blue-500', 'text-amber-500');
                } else {
                    document.getElementById('result-subtext').textContent = "Excellent foundation! We've adjusted the focus towards advanced concepts to push your boundaries.";
                    circle.classList.replace('text-blue-500', 'text-emerald-500');
                }

                // Render Markdown content
                document.getElementById('lesson-content').innerHTML = marked.parse(data.content);
                showLearningStep('content');

            } catch (err) {
                console.error(err);
                showError("Failed to generate content. Please try again.");
                showLearningStep('quiz');
            } finally {
                toggleLoading(false);
            }
        }

        // Boot
        window.onload = initApp;
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    print("Starting NexusEdu AI Platform (Flask Server)...")
    print("Access the app at http://localhost:5000")
    app.run(debug=True, port=5000)
