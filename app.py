import os
import sqlite3
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
DATABASE = os.environ.get("DATABASE_PATH", "bloodbridge.db")

BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
PRIORITIES = ["CRITICAL", "URGENT", "REQUIRED"]

# Compatible donor -> requested blood group (simplified whole-blood MVP logic).
COMPATIBILITY = {
    "A+": ["A+", "AB+"], "A-": ["A+", "A-", "AB+", "AB-"],
    "B+": ["B+", "AB+"], "B-": ["B+", "B-", "AB+", "AB-"],
    "AB+": ["AB+"], "AB-": ["AB+", "AB-"],
    "O+": ["O+", "A+", "B+", "AB+"],
    "O-": BLOOD_GROUPS,
}

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'donor',
        blood_group TEXT,
        city TEXT,
        phone TEXT,
        credits INTEGER NOT NULL DEFAULT 0,
        last_donation TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS hospitals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        city TEXT,
        phone TEXT,
        verified INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_name TEXT NOT NULL,
        blood_group TEXT NOT NULL,
        units INTEGER NOT NULL,
        priority TEXT NOT NULL,
        hospital_name TEXT NOT NULL,
        hospital_email TEXT NOT NULL,
        city TEXT NOT NULL,
        medical_note TEXT,
        status TEXT NOT NULL DEFAULT 'PENDING',
        verified INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        fulfilled_at TEXT
    );

    CREATE TABLE IF NOT EXISTS donations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        donor_id INTEGER NOT NULL,
        units INTEGER NOT NULL DEFAULT 1,
        credits_awarded INTEGER NOT NULL DEFAULT 10,
        hospital_name TEXT,
        donation_date TEXT NOT NULL,
        verified INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(donor_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS support_cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        requested_units INTEGER NOT NULL,
        due_date TEXT,
        status TEXT NOT NULL DEFAULT 'OPEN',
        created_at TEXT NOT NULL,
        FOREIGN KEY(request_id) REFERENCES requests(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)
    # Demo admin account; change/remove before production.
    admin = db.execute("SELECT id FROM users WHERE email=?", ("admin@bloodbridge.local",)).fetchone()
    if not admin:
        db.execute(
            "INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)",
            ("BloodBridge Admin", "admin@bloodbridge.local", "admin123", "admin", datetime.utcnow().isoformat())
        )
    db.commit()
    db.close()

def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    db.close()
    return user

def login_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Please log in first.", "warning")
                return redirect(url_for("login"))
            if role and user["role"] != role:
                flash("You do not have permission for this page.", "danger")
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator

@app.context_processor
def inject_globals():
    return {"current_user": current_user(), "blood_groups": BLOOD_GROUPS}

@app.route("/")
def index():
    db = get_db()
    stats = {
        "donors": db.execute("SELECT COUNT(*) c FROM users WHERE role='donor'").fetchone()["c"],
        "requests": db.execute("SELECT COUNT(*) c FROM requests").fetchone()["c"],
        "fulfilled": db.execute("SELECT COUNT(*) c FROM requests WHERE status='FULFILLED'").fetchone()["c"],
        "credits": db.execute("SELECT COALESCE(SUM(credits),0) c FROM users WHERE role='donor'").fetchone()["c"],
    }
    urgent = db.execute("""
        SELECT * FROM requests
        WHERE status IN ('PENDING','MATCHING') AND verified=1
        ORDER BY CASE priority WHEN 'CRITICAL' THEN 1 WHEN 'URGENT' THEN 2 ELSE 3 END,
                 datetime(created_at) ASC LIMIT 6
    """).fetchall()
    db.close()
    return render_template("index.html", stats=stats, urgent=urgent)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        blood_group = request.form.get("blood_group")
        city = request.form.get("city", "").strip()
        phone = request.form.get("phone", "").strip()

        if not name or not email or not password:
            flash("Name, email and password are required.", "danger")
            return redirect(url_for("register"))

        db = get_db()
        try:
            db.execute("""INSERT INTO users
                (name,email,password,role,blood_group,city,phone,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (name,email,password,"donor",blood_group,city,phone,datetime.utcnow().isoformat()))
            db.commit()
            flash("Account created. You can now log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("That email is already registered.", "danger")
        finally:
            db.close()
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=? AND password=?", (email,password)).fetchone()
        db.close()
        if user:
            session["user_id"] = user["id"]
            flash(f"Welcome, {user['name']}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required()
def dashboard():
    user = current_user()
    db = get_db()
    donations = db.execute("SELECT * FROM donations WHERE donor_id=? ORDER BY donation_date DESC", (user["id"],)).fetchall()
    open_requests = db.execute("""
        SELECT * FROM requests WHERE status IN ('PENDING','MATCHING') AND verified=1
        ORDER BY CASE priority WHEN 'CRITICAL' THEN 1 WHEN 'URGENT' THEN 2 ELSE 3 END,
                 datetime(created_at) ASC
    """).fetchall()
    supports = db.execute("""
        SELECT s.*, r.patient_name, r.blood_group, r.hospital_name
        FROM support_cases s JOIN requests r ON r.id=s.request_id
        WHERE s.user_id=? ORDER BY s.created_at DESC
    """, (user["id"],)).fetchall()
    db.close()
    return render_template("dashboard.html", user=user, donations=donations, open_requests=open_requests, supports=supports)

@app.route("/donate", methods=["POST"])
@login_required("donor")
def donate():
    user = current_user()
    if not user["blood_group"]:
        flash("Please complete your blood group in your profile before recording a donation.", "warning")
        return redirect(url_for("dashboard"))

    donation_date = request.form.get("donation_date") or date.today().isoformat()
    hospital = request.form.get("hospital_name", "Verified partner hospital").strip()
    credits = 10
    db = get_db()
    db.execute("""INSERT INTO donations(donor_id,units,credits_awarded,hospital_name,donation_date,verified)
                  VALUES(?,?,?,?,?,1)""", (user["id"],1,credits,hospital,donation_date))
    db.execute("UPDATE users SET credits=credits+?, last_donation=? WHERE id=?", (credits,donation_date,user["id"]))
    db.commit()
    db.close()
    flash(f"Donation recorded. {credits} community credits added after verification.", "success")
    return redirect(url_for("dashboard"))

@app.route("/profile", methods=["POST"])
@login_required("donor")
def profile():
    user = current_user()
    db = get_db()
    db.execute("""UPDATE users SET blood_group=?, city=?, phone=? WHERE id=?""",
               (request.form.get("blood_group"), request.form.get("city","").strip(),
                request.form.get("phone","").strip(), user["id"]))
    db.commit()
    db.close()
    flash("Profile updated.", "success")
    return redirect(url_for("dashboard"))

@app.route("/request-blood", methods=["GET","POST"])
@login_required()
def request_blood():
    if request.method == "POST":
        patient = request.form["patient_name"].strip()
        blood = request.form["blood_group"]
        units = max(1, int(request.form.get("units",1)))
        priority = request.form["priority"]
        hospital = request.form["hospital_name"].strip()
        hospital_email = request.form["hospital_email"].strip().lower()
        city = request.form["city"].strip()
        note = request.form.get("medical_note","").strip()

        db = get_db()
        # MVP: requests are created as unverified; admin/hospital must verify before matching.
        db.execute("""INSERT INTO requests
            (patient_name,blood_group,units,priority,hospital_name,hospital_email,city,medical_note,status,verified,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (patient,blood,units,priority,hospital,hospital_email,city,note,"PENDING",0,datetime.utcnow().isoformat()))
        db.commit()
        db.close()
        flash("Emergency request submitted. It must be verified by an authorized hospital/admin before matching.", "success")
        return redirect(url_for("dashboard"))
    return render_template("request_blood.html")

@app.route("/support/<int:request_id>", methods=["POST"])
@login_required()
def support(request_id):
    user = current_user()
    db = get_db()
    req = db.execute("SELECT * FROM requests WHERE id=? AND verified=1", (request_id,)).fetchone()
    if not req:
        db.close()
        flash("This request is not available for community support.", "danger")
        return redirect(url_for("dashboard"))
    due = (date.today() + timedelta(days=90)).isoformat()
    db.execute("""INSERT INTO support_cases(request_id,user_id,requested_units,due_date,status,created_at)
                  VALUES(?,?,?,?,?,?)""",
               (request_id,user["id"],req["units"],due,"OPEN",datetime.utcnow().isoformat()))
    db.commit()
    db.close()
    flash("Emergency support case created. This is a community contribution commitment, not a financial debt.", "success")
    return redirect(url_for("dashboard"))

@app.route("/api/matches/<int:request_id>")
@login_required()
def matches(request_id):
    db = get_db()
    req = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
    if not req:
        db.close()
        return jsonify({"error":"Request not found"}),404
    donor_groups = [g for g, targets in COMPATIBILITY.items() if req["blood_group"] in targets]
    placeholders = ",".join(["?"] * len(donor_groups))
    donors = db.execute(f"""
        SELECT id,name,blood_group,city,phone,credits,last_donation
        FROM users WHERE role='donor' AND blood_group IN ({placeholders})
        ORDER BY CASE WHEN city=? THEN 0 ELSE 1 END, credits DESC
        LIMIT 25
    """, (*donor_groups, req["city"])).fetchall()
    db.close()
    return jsonify([dict(d) for d in donors])

@app.route("/admin")
@login_required("admin")
def admin():
    db = get_db()
    requests = db.execute("SELECT * FROM requests ORDER BY datetime(created_at) DESC").fetchall()
    donors = db.execute("SELECT * FROM users WHERE role='donor' ORDER BY credits DESC").fetchall()
    hospitals = db.execute("SELECT * FROM hospitals ORDER BY id DESC").fetchall()
    stats = {
        "donors": len(donors),
        "requests": len(requests),
        "pending": sum(1 for r in requests if r["status"] == "PENDING"),
        "fulfilled": sum(1 for r in requests if r["status"] == "FULFILLED"),
    }
    db.close()
    return render_template("admin.html", requests=requests, donors=donors, hospitals=hospitals, stats=stats)

@app.route("/admin/request/<int:request_id>/verify", methods=["POST"])
@login_required("admin")
def verify_request(request_id):
    db = get_db()
    db.execute("UPDATE requests SET verified=1,status='MATCHING' WHERE id=?", (request_id,))
    db.commit()
    db.close()
    flash("Request verified and opened for matching.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/request/<int:request_id>/fulfill", methods=["POST"])
@login_required("admin")
def fulfill_request(request_id):
    db = get_db()
    db.execute("UPDATE requests SET status='FULFILLED',fulfilled_at=? WHERE id=?",
               (datetime.utcnow().isoformat(),request_id))
    db.commit()
    db.close()
    flash("Request marked as fulfilled.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/request/<int:request_id>/reject", methods=["POST"])
@login_required("admin")
def reject_request(request_id):
    db = get_db()
    db.execute("UPDATE requests SET status='REJECTED' WHERE id=?", (request_id,))
    db.commit()
    db.close()
    flash("Request rejected.", "warning")
    return redirect(url_for("admin"))

@app.route("/health")
def health():
    return {"status":"ok","service":"BloodBridge"}

init_db()

if __name__ == "__main__":
    app.run(debug=True)
